import os
import signal

from DicomFlowLib.conf import load_configs
from DicomFlowLib.mq import PubModel, SubModel
from DicomFlowLib.fs import FileStorageClient

from DicomFlowLib.log import CollectiveLogger
from DicomFlowLib.mq import MQSub
from fingerprinter import Fingerprinter


class Main:
    def __init__(self, config):
        signal.signal(signal.SIGTERM, self.stop)

        self.running = True

        self.logger = CollectiveLogger(name=config["LOG_NAME"],
                                       log_level=int(config["LOG_LEVEL"]),
                                       log_format=config["LOG_FORMAT"],
                                       log_dir=config["LOG_DIR"],
                                       rabbit_hostname=config["RABBIT_HOSTNAME"],
                                       rabbit_port=int(config["RABBIT_PORT"]),
                                       pub_models=[PubModel(**d) for d in config["LOG_PUB_MODELS"]])

        self.fs = FileStorageClient(logger=self.logger,
                                    file_storage_url=config["FILE_STORAGE_URL"])

        self.fp = Fingerprinter(logger=self.logger,
                                file_storage=self.fs,
                                flow_directory=config["FLOW_DIRECTORY"],
                                routing_key_success=config["PUB_ROUTING_KEY_SUCCESS"],
                                routing_key_fail=config["PUB_ROUTING_KEY_FAIL"]
                                )

        self.mq = MQSub(logger=self.logger,
                        work_function=self.fp.mq_entrypoint,
                        rabbit_hostname=config["RABBIT_HOSTNAME"],
                        rabbit_port=int(config["RABBIT_PORT"]),
                        pub_models=[PubModel(**d) for d in config["PUB_MODELS"]],
                        sub_models=[SubModel(**d) for d in config["SUB_MODELS"]],
                        sub_prefetch_value=int(config["SUB_PREFETCH_COUNT"]),
                        sub_queue_kwargs=config["SUB_QUEUE_KWARGS"],
                        pub_routing_key_error=config["PUB_ROUTING_KEY_ERROR"])

    def start(self):
        
        self.mq.start()
        while self.running:
            try:
                self.mq.join(timeout=5)
                if self.mq.is_alive():
                    pass
                else:
                    self.stop()
            except KeyboardInterrupt:
                self.stop()

    def stop(self, signalnum=None, stack_frame=None):
        self.running = False
        self.mq.stop()
        self.logger.stop()


if __name__ == "__main__":
    config = load_configs(os.environ["CONF_DIR"], os.environ["CURRENT_CONF"])

    m = Main(config=config)
    m.start()
