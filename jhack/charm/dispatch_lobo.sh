#!/bin/sh

# template filled in by jhack
DISABLED={%DISABLED%}

# special case: full lobotomy
if [ "$DISABLED" = "ALL" ]
then
  juju-log full lobotomy ACTIVE: event "${JUJU_DISPATCH_PATH}" ignored.
  exit 0
fi

case ",$JUJU_DISPATCH_PATH," in
  (*,"$DISABLED",*)
   juju-log selective lobotomy ACTIVE: event "${JUJU_DISPATCH_PATH}" ignored.;;
  (*) exec ./dispatch.ori;;
esac
