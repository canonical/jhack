import enum


class DeferralStatus(str, enum.Enum):
    null = "null"
    deferred = "deferred"
    reemitted = "reemitted"
    bounced = "bounced"
