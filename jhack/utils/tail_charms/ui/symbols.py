# todo: should we have a "console compatibility mode" using ascii?
from jhack.utils.tail_charms.core.deferral_status import DeferralStatus

fire_symbol = "🔥"
bomb_symbol = "❌"
fire_symbol_ascii = "*"
lobotomy_symbol = "✂"
replay_symbol = "⟳"

deferral_status_to_symbol = {
    DeferralStatus.null: "●",  # "●•⭘" not all alternatives supported on all consoles
    DeferralStatus.deferred: "❮",
    DeferralStatus.reemitted: "❯",
    DeferralStatus.bounced: "",
}
