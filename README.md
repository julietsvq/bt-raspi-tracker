# Bluetooth devices Sensor MQTT Client/Daemon

A simple Linux python script to query bluetooth devices, including the Mi Flora plant and the Airthings Wave Plus sensor, and send the data to an **MQTT** broker,
e.g., the famous [Eclipse Mosquitto](https://projects.eclipse.org/projects/technology.mosquitto).
After data made the hop to the MQTT broker it can be used by home automation software, like [openHAB](https://openhab.org) or Home Assistant.

![Demo gif for command line execution](demo.gif)

The program can be executed in **daemon mode** to run continuously in the background, e.g., as a systemd service.

Based on: 
* https://github.com/open-homeautomation/miflora
* https://github.com/ThomDietrich/miflora-mqtt-daemon
* https://github.com/Airthings/waveplus-reader
* https://thingsmatic.com/2017/02/01/self-monitoring-a-raspberry-pi-with-mqtt/

## About Mi Flora
* [Xiaomi Mi Flora sensors](https://xiaomi-mi.com/sockets-and-sensors/xiaomi-huahuacaocao-flower-care-smart-monitor) are meant to keep your plants alive by monitoring soil moisture, soil conductivity and light conditions.

## About Airthings Wave Plus
* [Airthings Wave Plus](https://www.airthings.com/en/wave-plus) is an indoor air quality sensor with radon detection, humidity, temperature, VOCs, CO2 and air pressure.

## Features

* Currently monitors: Mi Flora sensors, Airthings Wave Plus device, Raspberry Pi temperature (in case you wish to place it outside)
* Tested with Mi Flora firmware 3.2.1
* Tested with VegTrug firmware 3.3.1 (MAC prefix "80:EA:CA")
* Tested on Raspberry Pi 4
* Highly configurable
* Data publication via MQTT
* Configurable topic and payload
* MQTT authentication support
* No special/root privileges needed
* Linux daemon / systemd service, sd\_notify messages generated

### Readings

The Mi Flora sensor offers the following plant and soil readings:

| Name            | Description |
|-----------------|-------------|
| `temperature`   | Air temperature, in [°C] (0.1°C resolution) |
| `light`         | [Sunlight intensity](https://aquarium-digest.com/tag/lumenslux-requirements-of-a-cannabis-plant/), in [lux] |
| `moisture`      | [Soil moisture](https://observant.zendesk.com/hc/en-us/articles/208067926-Monitoring-Soil-Moisture-for-Optimal-Crop-Growth), in [%] |
| `conductivity`  | [Soil fertility](https://www.plantcaretools.com/measure-fertilization-with-ec-meters-for-plants-faq), in [µS/cm] |
| `battery`       | Sensor battery level, in [%] |

## Prerequisites

An MQTT broker is needed as the counterpart for this daemon.
MQTT is huge help in connecting different parts of your smart home and setting up of a broker is quick and easy.

## Installation

On a modern Linux system just a few steps are needed to get the daemon working.
The following example shows the installation under Raspbian below the `/opt` directory:

```shell
sudo apt install git python3 python3-pip bluetooth bluez

git clone https://github.com/julietsvq/bt-raspi-tracker.git /opt/bt_tracker

cd /opt/bt_tracker
sudo pip3 install -r requirements.txt
```

The daemon depends on `gatttool`, an external tool provided by the package `bluez` installed just now.
Make sure gatttool is available on your system by executing the command once:

```shell
gatttool --help
```

## Configuration

To match personal needs, all operation details can be configured using the file [`config.ini`](config.ini.dist).
The file needs to be created first:

```shell
cp /opt/bt_tracker/config.{ini.dist,ini}
vim /opt/bt_tracker/config.ini
```

**Attention:**
You need to add at least one sensor to the configuration.
Scan for available Mi Flora sensors in your proximity with the command:

```shell
$> sudo hcitool lescan | egrep 'Name|Flower care'

LE Scan ...
C4:7C:8D:62:72:49 Flower care
C4:7C:8D:62:40:29 Flower care
```

Scan for other bluethooth devices: 

```shell
$> sudo hcitool lescan
```

By the way:
Interfacing your Mi Flora sensor with this program is harmless.
The device will not be modified and will still work with the official smartphone app.

## Execution

A first test run is as easy as:

```shell
python3 /opt/bt_tracker/bt_tracker.py
```

Pay attention to communication errors due to distance related weak Bluetooth connections.

Using the command line argument `--config`, a directory where to read the config.ini file from can be specified, e.g.

```shell
python3 /opt/bt_tracker/bt_tracker.py --config /opt/bt_tracker-config
```

### Continuous Daemon/Service

You most probably want to execute the program **continuously in the background**.
This can be done either by using the internal daemon or cron.

**Attention:** Daemon mode must be enabled in the configuration file (default).

1. Systemd service - on systemd powered systems the **recommended** option

   ```shell
   sudo cp /opt/bt_tracker/template.service /etc/systemd/system/bt_tracker.service

   sudo systemctl daemon-reload

   sudo systemctl start bt_tracker.service
   sudo systemctl status bt_tracker.service

   sudo systemctl enable bt_tracker.service
   ```

To see daemon logs: 
   ```shell
journalctl -u bttracker.service --since "1 minutes ago"
   ```

## Integration

Data will be published to the MQTT broker topic "sensor/sensorname`" (e.g. `sensor/raspberrypi_temp`).
Data for the MiFlora sensors will be published to the MQTT broker topic "miflora/sensorname`" (e.g. `miflora/petunia`).

This data can be subscribed to and processed by other applications.
From this point forward your options are endless.

Enjoy!

----

## Disclaimer and Legal

> *Xiaomi* and *Mi Flora* are registered trademarks of *BEIJING XIAOMI TECHNOLOGY CO., LTD.*
>
> This project is a community project not for commercial use.
> The authors will not be held responsible in the event of device failure or withered plants.
>
> This project is in no way affiliated with, authorized, maintained, sponsored or endorsed by *Xiaomi* or any of its affiliates or subsidiaries.
