import os
import signal

from DicomFlowLib.conf import load_configs
from DicomFlowLib.data_structures.contexts import SubModel, PubModel
from DicomFlowLib.log import CollectiveLogger
from DicomFlowLib.mq import MQSub
from flow_tracker import FlowTracker


class Main:
    def __init__(self, config):
        signal.signal(signal.SIGTERM, self.stop)
        self.running = False
        self.logger = CollectiveLogger(name=config["LOG_NAME"],
                                       log_level=int(config["LOG_LEVEL"]),
                                       log_format=config["LOG_FORMAT"],
                                       log_dir=config["LOG_DIR"],
                                       rabbit_hostname=config["RABBIT_HOSTNAME"],
                                       rabbit_port=int(config["RABBIT_PORT"]),
                                       pub_models=[PubModel(**d) for d in config["LOG_PUB_MODELS"]],
                                       )

        self.ft = FlowTracker(logger=self.logger,
                              database_path=config["DATABASE_PATH"],
                              dashboard_rules=config["DASHBOARD_RULES"])

        self.mq = MQSub(logger=self.logger,
                        work_function=self.ft.mq_entrypoint,
                        rabbit_hostname=config["RABBIT_HOSTNAME"],
                        rabbit_port=int(config["RABBIT_PORT"]),
                        sub_models=[SubModel(**d) for d in config["SUB_MODELS"]],
                        pub_models=[],
                        sub_prefetch_value=int(config["SUB_PREFETCH_COUNT"]),
                        sub_queue_kwargs=config["SUB_QUEUE_KWARGS"])

    def start(self):
        self.logger.debug("Starting Janitor", finished=False)
        self.running = True
        
        self.mq.start()
        self.logger.debug("Starting Janitor", finished=True)

        while self.running:
            try:
                self.mq.join(timeout=5)
                if self.mq.is_alive():
                    pass
                else:
                    self.stop()
            except KeyboardInterrupt:
                self.stop()

    def stop(self):
        self.logger.debug("Stopping Janitor", finished=False)
        self.running = False
        self.ft.stop()
        self.logger.stop()

        self.ft.join()
        self.logger.debug("Stopping Janitor", finished=True)


if __name__ == "__main__":
    config = load_configs(os.environ["CONF_DIR"])

    m = Main(config=config)
    m.start()
