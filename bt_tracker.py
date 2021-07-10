#!/usr/bin/env python3

import ssl
import sys
import re
import json
import os.path
import argparse
from time import time, sleep, localtime, strftime
from collections import OrderedDict
from colorama import init as colorama_init
from colorama import Fore, Back, Style
from configparser import ConfigParser
from unidecode import unidecode
from miflora.miflora_poller import MiFloraPoller, MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE
from btlewrap import BluepyBackend, GatttoolBackend, BluetoothBackendException
from bluepy.btle import BTLEException, UUID, Peripheral, Scanner, DefaultDelegate
import paho.mqtt.client as mqtt
import sdnotify
from signal import signal, SIGPIPE, SIG_DFL
from subprocess import check_output
from re import findall
from wavethings import Sensors, WavePlus, AIR_HUMIDITY, AIR_RADON_ST, AIR_RADON_LT, AIR_TEMPERATURE, AIR_PRESSURE, AIR_CO2, AIR_VOC, SENSOR_IDX_HUMIDITY, SENSOR_IDX_RADON_SHORT_TERM_AVG, SENSOR_IDX_RADON_LONG_TERM_AVG, SENSOR_IDX_TEMPERATURE, SENSOR_IDX_REL_ATM_PRESSURE, SENSOR_IDX_CO2_LVL, SENSOR_IDX_VOC_LVL
signal(SIGPIPE,SIG_DFL)

project_name = 'Bluetooth Tracker MQTT Client/Daemon'
project_url = 'https://github.com/julietsvq/bt-raspi-tracker'

parameters = OrderedDict([
    (MI_LIGHT, dict(name="LightIntensity", name_pretty='Sunlight Intensity', typeformat='%d', unit='lux', device_class="illuminance")),
    (MI_TEMPERATURE, dict(name="AirTemperature", name_pretty='Air Temperature', typeformat='%.1f', unit='°C', device_class="temperature")),
    (MI_MOISTURE, dict(name="SoilMoisture", name_pretty='Soil Moisture', typeformat='%d', unit='%', device_class="humidity")),
    (MI_CONDUCTIVITY, dict(name="SoilConductivity", name_pretty='Soil Conductivity/Fertility', typeformat='%d', unit='µS/cm')),
    (MI_BATTERY, dict(name="Battery", name_pretty='Sensor Battery Level', typeformat='%d', unit='%', device_class="battery"))
])

if False:
    # will be caught by python 2.7 to be illegal syntax
    print('Sorry, this script requires a python3 runtime environment.', file=sys.stderr)

# Argparse
parser = argparse.ArgumentParser(description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument('--config_dir', help='set directory where config.ini is located', default=sys.path[0])
parse_args = parser.parse_args()

# Intro
colorama_init()
print(Fore.GREEN + Style.BRIGHT)
print(project_name)
print('Source:', project_url)
print(Style.RESET_ALL)

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

# Logging function
def print_line(text, error = False, warning=False, sd_notify=False, console=True):
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if console:
        if error:
            print(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL, file=sys.stderr)
        elif warning:
            print(Fore.YELLOW + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
        else:
            print(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
    timestamp_sd = strftime('%b %d %H:%M:%S', localtime())
    if sd_notify:
        sd_notifier.notify('STATUS={} - {}.'.format(timestamp_sd, unidecode(text)))

# Identifier cleanup
def clean_identifier(name):
    clean = name.strip()
    for this, that in [[' ', '-'], ['ä', 'ae'], ['Ä', 'Ae'], ['ö', 'oe'], ['Ö', 'Oe'], ['ü', 'ue'], ['Ü', 'Ue'], ['ß', 'ss']]:
        clean = clean.replace(this, that)
    clean = unidecode(clean)
    return clean

# Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print_line('MQTT connection established', console=True, sd_notify=True)
        print()
    else:
        print_line('Connection error with result code {} - {}'.format(str(rc), mqtt.connack_string(rc)), error=True)
        #kill main thread
        os._exit(1)


def on_publish(client, userdata, mid):
    #print_line('Data successfully published.')
    pass

def get_temp():
    temp = check_output(["vcgencmd","measure_temp"]).decode("UTF-8")
    return(findall("\d+\.\d+",temp)[0])

# Load configuration file
config_dir = parse_args.config_dir

config = ConfigParser(delimiters=('=', ), inline_comment_prefixes=('#'))
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

used_adapter = config['General'].get('adapter', 'hci0')
daemon_enabled = config['Daemon'].getboolean('enabled', True)

default_miflora_base_topic = 'miflora'
default_sensor_base_topic = 'sensor'

miflora_base_topic = config['MQTT'].get('miflora_base_topic', default_miflora_base_topic).lower()
sensor_base_topic = config['MQTT'].get('sensor_base_topic', default_sensor_base_topic).lower()
sleep_period = config['Daemon'].getint('period', 300)
miflora_cache_timeout = sleep_period - 1

# Check configuration
if not config['Sensors']:
    print_line('No sensors found in configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

if not config['Airthings']:
    print_line('You need to specify your Airthings Wave Plus device serial number in configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

serial_number = config['Airthings'].getint('serial_number')

print_line('Configuration accepted', console=False, sd_notify=True)

# MQTT connection
print_line('Connecting to MQTT broker ...')
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish
mqtt_client.will_set('{}/$announce'.format(miflora_base_topic), payload='{}', retain=True)

if config['MQTT'].getboolean('tls', False):
    # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest protocol version
    # that both the client and server support. Despite the name, this option can select
    # “TLS” protocols as well as “SSL”" - so this seems like a resonable default
    mqtt_client.tls_set(
        ca_certs=config['MQTT'].get('tls_ca_cert', None),
        keyfile=config['MQTT'].get('tls_keyfile', None),
        certfile=config['MQTT'].get('tls_certfile', None),
        tls_version=ssl.PROTOCOL_SSLv23
    )

mqtt_username = os.environ.get("MQTT_USERNAME", config['MQTT'].get('username'))
mqtt_password = os.environ.get("MQTT_PASSWORD", config['MQTT'].get('password', None))

if mqtt_username:
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
try:
    mqtt_client.connect(os.environ.get('MQTT_HOSTNAME', config['MQTT'].get('hostname', 'localhost')),
                        port=int(os.environ.get('MQTT_PORT', config['MQTT'].get('port', '1883'))),
                        keepalive=config['MQTT'].getint('keepalive', 60))
except:
    print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

sd_notifier.notify('READY=1')

# Initialize Mi Flora sensors
flores = OrderedDict()
for [name, mac] in config['Sensors'].items():
    if not re.match("[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}", mac.lower()):
        print_line('The MAC address "{}" seems to be in the wrong format. Please check your configuration'.format(mac), error=True, sd_notify=True)
        sys.exit(1)

    if '@' in name:
        name_pretty, location_pretty = name.split('@')
    else:
        name_pretty, location_pretty = name, ''
    name_clean = clean_identifier(name_pretty)
    location_clean = clean_identifier(location_pretty)

    flora = OrderedDict()
    print('Adding sensor to device list and testing connection ...')
    print('Name:          "{}"'.format(name_pretty))
    # print_line('Attempting initial connection to Mi Flora sensor "{}" ({})'.format(name_pretty, mac), console=False, sd_notify=True)

    flora_poller = MiFloraPoller(mac=mac, backend=BluepyBackend, cache_timeout=miflora_cache_timeout, retries=3, adapter=used_adapter)
    flora['poller'] = flora_poller
    flora['name_pretty'] = name_pretty
    flora['mac'] = flora_poller._mac
    flora['refresh'] = sleep_period
    flora['location_clean'] = location_clean
    flora['location_pretty'] = location_pretty
    flora['stats'] = {"count": 0, "success": 0, "failure": 0}
    flora['firmware'] = "0.0.0"
    try:
        flora_poller.fill_cache()
        flora_poller.parameter_value(MI_LIGHT)
        flora['firmware'] = flora_poller.firmware_version()
    except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
        print_line('Initial connection to Mi Flora sensor "{}" ({}) failed due to exception: {}'.format(name_pretty, mac, e), error=True, sd_notify=True)
    else:
        print('Internal name: "{}"'.format(name_clean))
        print('Device name:   "{}"'.format(flora_poller.name()))
        print('MAC address:   {}'.format(flora_poller._mac))
        print('Firmware:      {}'.format(flora_poller.firmware_version()))
        print_line('Initial connection to Mi Flora sensor "{}" ({}) successful'.format(name_pretty, mac), sd_notify=True)
        if int(flora_poller.firmware_version().replace(".", "")) < 319:
            print_line('Mi Flora sensor with a firmware version before 3.1.9 is not supported. Please update now.'.format(name_pretty, mac), error=True, sd_notify=True)

    print()
    flores[name_clean] = flora

print_line('Initialization complete, starting MQTT publish loop', console=False, sd_notify=True)


# Sensor data retrieval and publication
while True:

    # Raspberry Pi 4 temperature
    print_line('Retrieving temperature from Raspberry Pi ...')
    raspi_temp = get_temp()
    print_line('Result: {}'.format(json.dumps(raspi_temp)))
    print_line('Publishing to MQTT topic "{}/{}"'.format(sensor_base_topic, 'raspberrypi_temp'))
    print()
    mqtt_client.publish('{}/{}'.format(sensor_base_topic, 'raspberrypi_temp'), json.dumps(raspi_temp))
    sleep(0.5)

    # Airthings Wave Plus
    try:
        print_line('Retrieving data from Airthings Wave Plus device with serial number {} ...'.format(serial_number))
        waveplus = WavePlus(serial_number)    

        air_data = OrderedDict()
        waveplus.connect()
        sensors = waveplus.read()
        
        air_data[AIR_HUMIDITY] = str(sensors.getValue(SENSOR_IDX_HUMIDITY))
        air_data[AIR_RADON_ST] = str(sensors.getValue(SENSOR_IDX_RADON_SHORT_TERM_AVG))
        air_data[AIR_RADON_LT] = str(sensors.getValue(SENSOR_IDX_RADON_LONG_TERM_AVG))
        air_data[AIR_TEMPERATURE] = str(sensors.getValue(SENSOR_IDX_TEMPERATURE))
        air_data[AIR_PRESSURE] = str(sensors.getValue(SENSOR_IDX_REL_ATM_PRESSURE))
        air_data[AIR_CO2] = str(sensors.getValue(SENSOR_IDX_CO2_LVL))
        air_data[AIR_VOC] = str(sensors.getValue(SENSOR_IDX_VOC_LVL))
              
        waveplus.disconnect()
        print_line('Result: {}'.format(json.dumps(air_data)))
        print_line('Publishing to MQTT topic "{}/{}"'.format(sensor_base_topic, 'airthings'))
        print()
        mqtt_client.publish('{}/{}'.format(sensor_base_topic, 'airthings'), json.dumps(air_data))
        sleep(0.5)
    except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
      print('An exception occurred while trying to connect to the Airthings Wave Plus device:')
      print('{}'.format(e))
    finally: 
        waveplus.disconnect()

    # MiFlora sensors
    for [flora_name, flora] in flores.items():
        data = OrderedDict()
        attempts = 2
        flora['poller']._cache = None
        flora['poller']._last_read = None
        flora['stats']['count'] += 1
        print_line('Retrieving data from sensor "{}" ...'.format(flora['name_pretty']))
        while attempts != 0 and not flora['poller']._cache:
            try:
                flora['poller'].fill_cache()
                flora['poller'].parameter_value(MI_LIGHT)
            except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
                attempts -= 1
                if attempts > 0:
                    if len(str(e)) > 0:
                        print_line('Retrying due to exception: {}'.format(e), error=True)
                    else:
                        print_line('Retrying ...', warning=True)
                flora['poller']._cache = None
                flora['poller']._last_read = None

        if not flora['poller']._cache:
            flora['stats']['failure'] += 1
            flora['stats']['success'] += 1

        for param,_ in parameters.items():
            data[param] = flora['poller'].parameter_value(param)
        print_line('Result: {}'.format(json.dumps(data)))

        print_line('Publishing to MQTT topic "{}/{}"'.format(miflora_base_topic, flora_name))
        mqtt_client.publish('{}/{}'.format(miflora_base_topic, flora_name), json.dumps(data))
        sleep(0.5) # some slack for the publish roundtrip and callback function
        print()

    print_line('Status messages published', console=False, sd_notify=True)

    if daemon_enabled:
        print_line('Sleeping ({} seconds) ...'.format(sleep_period))
        sleep(sleep_period)
        print()
    else:
        print_line('Execution finished in non-daemon-mode', sd_notify=True)
        mqtt_client.disconnect()
        break


