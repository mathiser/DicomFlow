import json
from typing import Iterable, Dict, List

import pandas as pd
import pydicom

from DicomFlowLib.data_structures.contexts import FlowContext, PublishContext
from DicomFlowLib.log import CollectiveLogger
from .db import Database


class FlowTracker:
    def __init__(self,
                 logger: CollectiveLogger,
                 database_path: str,
                 dashboard_rules: List[Dict]):
        self.logger = logger
        self.engine = None
        self.database_url = None
        self.dashboard_rules = dashboard_rules
        self.database_path = database_path
        self.db = Database(logger=self.logger, database_path=self.database_path)

    def mq_entrypoint(self, basic_deliver, body) -> Iterable[PublishContext]:
        context = FlowContext(**json.loads(body.decode()))

        self.update_dashboard_rows(basic_deliver, context)
        return []

    def update_dashboard_rows(self, basic_deliver, context: FlowContext):
        for rule in self.dashboard_rules:
            if rule["on_exchange"] in [basic_deliver.exchange, "#"]:
                if basic_deliver.routing_key in rule["on_routing_keys"] or "#" in rule["on_routing_keys"]:
                    self.db.maybe_insert_row(uid=context.uid,
                                             name=context.flow.name,
                                             version=context.flow.version,
                                             patient=self.generate_pseudonym(context.dataframe),
                                             sender=context.sender.host,
                                             priority=context.flow.priority,
                                             destinations=", ".join([f"{d.ae_title} ({d.host})" for d in context.flow.destinations]))

                    self.db.set_status_of_row(context.uid, rule["status"])

    @staticmethod
    def generate_pseudonym(ds: pd.DataFrame):
        row = ds.iloc[0]
        cpr = str(row["PatientID"])[:4]
        full_name = str(row["PatientName"]).split("^")
        name = [name[0] for names in full_name for name in names.split(" ")]
        return cpr + "".join(name)
