import json
import tempfile
import time
import traceback
from io import BytesIO

import docker
from docker import types

from DicomFlowLib.data_structures.contexts.data_context import FlowContext
from DicomFlowLib.fs import FileStorage
from DicomFlowLib.log.logger import CollectiveLogger
from DicomFlowLib.mq import MQBase


class DockerConsumer:
    def __init__(self,
                 logger: CollectiveLogger,
                 file_storage: FileStorage,
                 pub_exchange: str,
                 pub_routing_key: str,
                 pub_routing_key_as_queue: bool,
                 pub_exchange_type: str,
                 gpu: str | bool):
        self.logger = logger
        self.fs = file_storage
        self.pub_exchange_type = pub_exchange_type
        self.pub_routing_key = pub_routing_key
        self.pub_routing_key_as_queue = pub_routing_key_as_queue
        self.pub_exchange = pub_exchange
        self.gpu = gpu
        self.cli = docker.from_env()

    def __del__(self):
        self.cli.close()

    def mq_entrypoint(self, connection, channel, basic_deliver, properties, body):
        mq = MQBase(self.logger).connect_with(connection=connection, channel=channel)

        context = FlowContext(**json.loads(body.decode()))

        self.logger.info(f"PROCESSING", uid=context.uid, finished=False)

        input_tar = self.fs.get(context.input_file_uid)

        output_tar = self.exec_model(context, input_tar)

        self.logger.info(f"RUNNING FLOW", uid=context.uid, finished=False)
        context.output_file_uid = self.fs.put(output_tar)
        self.logger.info(f"RUNNING FLOW", uid=context.uid, finished=True)

        self.logger.info(f"PUBLISHING RESULT", uid=context.uid, finished=False)
        mq.setup_exchange_callback(exchange=self.pub_exchange, exchange_type=self.pub_exchange_type)
        mq.setup_queue_and_bind_callback(exchange=self.pub_exchange,
                                routing_key=self.pub_routing_key,
                                routing_key_as_queue=self.pub_routing_key_as_queue)

        mq.basic_publish_callback(exchange=self.pub_exchange,
                         routing_key=self.pub_routing_key,
                         body=context.model_dump_json().encode())
        self.logger.info(f"PUBLISHING RESULT", uid=context.uid, finished=True)

        self.logger.info(f"PROCESSING", uid=context.uid, finished=True)

    def exec_model(self,
                   context: FlowContext,
                   input_tar: BytesIO) -> BytesIO:

        model = context.flow.model
        if model.pull_before_exec:
            self.cli.images.pull(*model.docker_kwargs["image"].split(":"))

        self.logger.info(f"RUNNING CONTAINER TAG: {model.docker_kwargs["image"]}", uid=context.uid, finished=False)

        kwargs = model.docker_kwargs
        # Mount point of input/output to container. These are dummy binds, to make sure the container has /input and /output
        # container.
        kwargs["volumes"] = [
            f"{tempfile.mkdtemp()}:{model.input_dir}:rw",  # is there a better way
            f"{tempfile.mkdtemp()}:{model.output_dir}:rw"
        ]

        # Allow GPU usage. If int, use as count, if str use as uuid
        if self.gpu:
            kwargs["ipc_mode"] = "host"
            if isinstance(self.gpu, str):
                kwargs["device_requests"] = [types.DeviceRequest(device_ids=[self.gpu], capabilities=[['gpu']])]
            else:
                kwargs["device_requests"] = [types.DeviceRequest(count=-1, capabilities=[['gpu']])]

        try:
            # Create container
            container = self.cli.containers.create(**kwargs)
            # Reload new params
            container.reload()

            if model.input_dir:
                 # Add the input tar to provided input
                 container.put_archive(model.input_dir, input_tar)

            container.start()
            container.wait()  # Blocks...
            self.logger.info("####### CONTAINER LOG ##########")
            self.logger.info(container.logs().decode())

            if model.output_dir:
                output, stats = container.get_archive(path=model.output_dir)

                # Write to a format I understand
                output_tar = BytesIO()
                for chunk in output:
                    output_tar.write(chunk)
                output_tar.seek(0)
                self.logger.info(f"RUNNING CONTAINER TAG: {model.docker_kwargs["image"]}", uid=context.uid,
                                 finished=True)
                return output_tar
                # # Remove one dir level
                # # output_tar = self.postprocess_output_tar(tarf=output_tar)
                #
                # return output_tar

        except Exception as e:
            self.logger.error(str(traceback.format_exc()))
            raise e
        finally:
            counter = 0
            while counter < 5:
                try:
                    self.logger.debug(f"Attempting to remove container {container.short_id}",
                                      uid=context.uid,
                                      finished=False)
                    container.remove()
                    self.logger.debug(f"Attempting to remove container {container.short_id}",
                                      uid=context.uid,
                                      finished=True)
                    break
                except:
                    self.logger.debug(f"Failed to remove {container.short_id}. Trying again in 5 sec...",
                                      uid=context.uid,
                                      finished=True)
                    counter += 1
                    time.sleep(5)