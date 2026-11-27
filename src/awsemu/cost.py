"""What the calls in the proxy's log would cost on AWS: an order of magnitude.

Only request charges, from AWS's public on-demand list prices for us-east-1 (see
``PRICES_AS_OF``): no free tier, storage, data transfer, provisioned capacity or
discounts. Units are approximations from what the log has:

* DynamoDB: one read or write request unit per call (two for transactions), though
  big items take more; Query and Scan count one unit per call, not per item read;
* Lambda: requests, plus duration from the proxy's latency at 128 MB (the latency
  includes the emulator's own overhead, so it errs high);
* CloudWatch Logs ingestion: from the request bytes of ``PutLogEvents``;
* Step Functions standard: one state transition per execution started (real
  workflows have more).

``--prices FILE`` replaces any price with your own (your Region, your discounts).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections.abc import Callable
from pathlib import Path

from . import services

PRICES_AS_OF = "2026-11"
REGION = "us-east-1"

# key -> (USD per unit, unit label)
PRICES: dict[str, tuple[float, str]] = {
    "dynamodb.write": (0.625 / 1e6, "write request unit"),
    "dynamodb.read": (0.125 / 1e6, "read request unit"),
    "sqs.standard": (0.40 / 1e6, "request"),
    "sqs.fifo": (0.50 / 1e6, "request"),
    "s3.put": (0.005 / 1e3, "PUT/COPY/POST/LIST request"),
    "s3.get": (0.0004 / 1e3, "GET and other request"),
    "sns.publish": (0.50 / 1e6, "publish"),
    "lambda.request": (0.20 / 1e6, "invocation"),
    "lambda.gb_second": (0.0000166667, "GB-second"),
    "secretsmanager.api": (0.05 / 1e4, "API call"),
    "kms.request": (0.03 / 1e4, "request"),
    "events.put": (1.00 / 1e6, "custom event"),
    "stepfunctions.transition": (0.025 / 1e3, "state transition"),
    "logs.ingest_gb": (0.50, "GB ingested"),
    "cloudwatch.put_metric": (0.01 / 1e3, "PutMetricData request"),
    "kinesis.put_unit": (0.014 / 1e6, "PUT payload unit (provisioned)"),
    "ssm.standard": (0.0, "standard parameter call"),
}
# Priced services awsemu has no registry module for (the others: each service's ``cost`` hook).
OTHER: dict[str, Callable[[dict], list[tuple[str, float]]]] = {
    "kms": lambda call: [("kms.request", 1)],
    "cloudwatch": lambda call: [("cloudwatch.put_metric", 1)] if call["operation"] == "PutMetricData" else [],
    "sts": lambda call: [],  # no request charge
}


@dataclass
class Line:
    service: str
    item: str
    units: float
    price: float
    unit_label: str

    @property
    def cost(self) -> float:
        return self.units * self.price


@dataclass
class Estimate:
    lines: list[Line] = field(default_factory=list)
    calls: int = 0
    unpriced: dict[str, int] = field(default_factory=dict)  # service -> calls with no price here

    @property
    def total(self) -> float:
        return sum(line.cost for line in self.lines)

    def by_service(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for line in self.lines:
            out[line.service] = out.get(line.service, 0.0) + line.cost
        return out

    def as_dict(self, runs: int = 1) -> dict:
        return {
            "estimate": True,
            "region": REGION,
            "prices_as_of": PRICES_AS_OF,
            "calls": self.calls,
            "runs": runs,
            "total_usd": round(self.total * runs, 6),
            "lines": [
                {
                    "service": x.service,
                    "item": x.item,
                    "units": x.units * runs,
                    "usd_per_unit": x.price,
                    "unit": x.unit_label,
                    "usd": round(x.cost * runs, 6),
                }
                for x in self.lines
            ],
            "not_priced": self.unpriced,
            "excludes": ["free tier", "storage", "data transfer", "provisioned capacity", "discounts"],
        }


def load_prices(path: Path | None) -> dict[str, tuple[float, str]]:
    prices = dict(PRICES)
    if path:
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            label = prices.get(key, (0, "unit"))[1]
            prices[key] = (float(value), label)
    return prices


def estimate(calls: list[dict], prices: dict[str, tuple[float, str]] | None = None) -> Estimate:
    prices = prices or PRICES
    units: dict[tuple[str, str], float] = {}
    out = Estimate()

    def add(service: str, key: str, n: float = 1.0) -> None:
        units[(service, key)] = units.get((service, key), 0.0) + n

    hooks = {**OTHER, **{s.name: s.cost for s in services.all_services() if s.cost}}
    for call in calls:
        service, op = call.get("service") or "", call.get("operation") or ""
        if not service or not op or call.get("status") == 0:  # unknown, or never answered
            continue
        out.calls += 1
        hook = hooks.get(service)
        if hook is None:
            out.unpriced[service] = out.unpriced.get(service, 0) + 1
            continue
        for key, n in hook(call):
            add(service, key, n)
    for (service, key), n in sorted(units.items()):
        price, label = prices.get(key, (0.0, "unit"))
        out.lines.append(Line(service, key.split(".", 1)[1], n, price, label))
    return out
