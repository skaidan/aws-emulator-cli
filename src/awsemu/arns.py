"""ARNs: parse ``arn:aws:SERVICE:REGION:ACCOUNT:RESOURCE`` and name its parts."""

from __future__ import annotations

from dataclasses import dataclass

import click


@dataclass
class Arn:
    service: str
    region: str
    account: str
    resource: str

    @property
    def kind(self) -> str:
        """``table/users`` -> ``table``; ``function:hi`` -> ``function``."""
        for sep in ("/", ":"):
            if sep in self.resource:
                return self.resource.split(sep, 1)[0]
        return ""

    @property
    def rest(self) -> str:
        """The resource without its kind prefix."""
        for sep in ("/", ":"):
            if sep in self.resource:
                return self.resource.split(sep, 1)[1]
        return self.resource


def parse_arn(text: str) -> Arn:
    parts = text.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn":
        raise click.BadParameter(f"'{text}' is not an ARN (arn:aws:SERVICE:REGION:ACCOUNT:RESOURCE)")
    return Arn(service=parts[2], region=parts[3], account=parts[4], resource=parts[5])
