# DicomFlow
DicomFlow is a extendable service-oriented framework to executed containerized workflows on DICOM files. 

## Intended Use
DicomFlow is provided as is and without any responsibility or warrenty by the authors. The author does not considered it a medical device under EU's Medical Device Regulation (MDR),
as it only facilitate recieving of, execution of docker containers on and finally sending of DICOM files. DicomFlow in it self does not manipulate any of the received data. 
Operations on data are limited to storing, lossless compression, mounting to containers, receiving and sending of dicom files. 

If used in a clinical/research setting, beaware that the docker containers should comply to MDR or any local legislation regarding medical devices.

## Get started
### Dependencies
DicomFlow should be able run in any environment with [Docker](https://www.docker.com/get-started/) installed. If the executed containers require GPU-support, [NVIDIA container toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
must be installed with appropriate dependiencies and a compatible GPU installed.

### Setting up DicomFlow
One you have dependencies set up, you can clone this repository and start up DicomFlow with docker compose:
```
git clone https://github.com/mathiser/DicomFlow
cd DicomFlow
docker compose up -d --build
```
If the services build successfully, you can inspect the logs of all services using `docker compose logs -f` and logs of a specific service with `docker compose logs -f {service name}`. 
Now you should have a DICOM receiver running by default on `localhost:10000` with the ae title: `STORESCU`.

### Defining a Flow
In DicomFlow, a "Flow" refers to the full of path of a dicom input through model execution an dicom sending to a different endpoint. Flows are defined in yaml files (one per flow) and mounted to `fingerprinter` in `/opt/DicomFlow/flows`.

Below is an example of the simplest possible flow. It triggers if any received dicom file is a CT. The resulting folder is not sent anywhere.
```
triggers:
  - Modality: CT
models:
  - docker_kwargs:
      image: hello-world
destinations: []
```
#### triggers
In `triggers` you can put dicom tags and regex patterns, all of which must be found among the incoming dicom files for the `models` to be executed.
`triggers` is a list of dictionaries, where all dictionary elements must be matched in the same file.
An example of a more complex triggers is given:

```
triggers:
  - Modality: "CT" # Matches if CT is contained in "Modality"
    SeriesDescription: "Head|Neck|Brain"  # Matches either Head, Neck or Brain in only the files with Modality: CT
  - SOPClassUID: "1.2.840.10008.5.1.4.1.1.4" # SOPClassUID for MRI
    StudyDescription: "AutoSegProtocol"
```

Regex can be tricky, so go ahead and try out your patterns in a [regex tester](https://regex101.com/)

#### models
In `models` the actual docker containers are defined. `models` are a list of definitions which are executed in sequence with the output of one container being input for the next.
Below is a more comprehensive definition of `models`, where input is copied to output twice, while the environment variable "CONTAINER_ORDER" is echoed in each, and GPU is used in the second container only.

```
models:
  - docker_kwargs:  # All variables in `docker_kwargs` are actually configured through the containers.run interface of [docker-py](https://docker-py.readthedocs.io/en/stable/containers.html), and thus almost any value can be used (some are not allowed per design)
      image: busybox
      command: sh -c 'echo $CONTAINER_ORDER; cp -r /input /output/'
      environment:
        CONTAINER_ORDER: 0
    gpu: False
    input_dir: /input/  # This is already default
    output_dir: /output/  # This is already default
    
  - docker_kwargs:
      image: busybox
      command: sh -c 'echo $CONTAINER_ORDER; cp -r /input /output/'
      environment:
        CONTAINER_ORDER: 1
    gpu: True  # Request GPU support
    input_dir: /input/
    output_dir: /output/
    timeout: 1800  # default timeout is 1800 seconds. If the container is running for longer, it will be terminated forcefully. This is to avoid hanging container jobs, which obstruct the queue.
    static_mount: "/home/DicomFlow/models/AwesomeModel1:/model:ro"  # giving the container access to static model. Note that if consumers are run on different nodes, this directory must exist on all.

```
#### destinations
`destinations` contains a list of dicom nodes to send all files from the last container's `output_dir` to. Below is an example:
```
destinations:
  - host: localhost
    port: 10001
    ae_title: STORESCP
  - host: storage.some-system.org
    port: 104
    ae_title: FANCYSTORE
```
#### Other variables
Furhtermore the following variables can be set in the flow definition:
##### priority
`priority` can be set to an integer between 0 and 5, where 5 is highest priority. 0 is default. When consumers are receiving a new flow to be run, the available flow with highest priority with run. 
Note, that priority makes flows jump the queue, but NOT pause running flows.


## Configuration
All services in DicomFlow are extensively configurable, but is by default configured to work as is. 

If you would like to change a configuration, you have two options. 
- Mount a .yaml file with the desired variables into the containers directory `/opt/DicomFlow/conf.d`.
- Set an environment variable in the docker compose file.
Configs are (over)loaded in the order:
- Defaults (found in `/opt/DicomFlow/conf.d/00_default_config.yaml`)
- `/opt/DicomFlow/conf.d` (alphabetically)
- Environment variables (order of occurence).

### Shared configurations
RabbitMQ must be configured on all services using the following variables:
```
# RabbitMQ
RABBIT_HOSTNAME: "localhost"
RABBIT_PORT: 5672
RABBIT_USERNAME: "guest"
RABBIT_PASSWORD: "guest"
```

Log level can be set with:
```
# Logging
LOG_LEVEL: 20
```

### Service specific configurations
In principle all variables in `/opt/DicomFlow/conf.d/00_default_config.yaml`, but probably should not. Below is a list of variables which should be adapted to the specific environment

#### STORESCP
The DICOM receiver can be adapted with the following variables
```
# SCP
AE_TITLE: "STORESCP"
AE_HOSTNAME: "localhost"
AE_PORT: 10000
PYNETDICOM_LOG_LEVEL: "standard"
```

By default, the receiver writes dicom files into a flat directory, which is mounted into the containers input mountpoint. This is set with the default: `TAR_SUBDIR: []`, which will result in the following container input:
- /input/
  - file1.dcm
  - file2.dcm
  - file3.dcm
  - file4.dcm
  - file5.dcm

When models are operating on multi modal input data, it may be desirable to seperate files into a directory already when they are received. To do this, TAR_SUBDIR can contain a list of dicom tags, to be used as subfolders.
As an example:
```
TAR_SUBDIR: 
  - SOPClassUID
  - SeriesInstanceUID
```
Which will results in something like:
- /input/
  - 1.2.840.10008.5.1.4.1.1.2
    - 1.1.1.1.1
      - CT1.dcm
      - CT2.dcm
      - ...
  - 1.2.840.10008.5.1.4.1.1.4
    - 1.1.1.1.1
      - MR_T1.dcm
      - ...
    - 2.2.2.2.2
      - MR1_T2.dcm

#### Fingerprinter
In the Fingerprinter, the actual behavior of container execution is configured.
