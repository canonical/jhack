#!/bin/sh
#DISABLED={%DISABLED%}  # jhack template

# special case: full lobotomy
if [ "$DISABLED" = "ALL" ]
then
  juju-log full lobotomy ACTIVE: event "${JUJU_DISPATCH_PATH}" ignored.
  exit 0
fi

case ",$DISABLED," in
  (*,"$JUJU_DISPATCH_PATH",*)
   juju-log selective lobotomy ACTIVE: event "${JUJU_DISPATCH_PATH}" ignored.;;
  (*) exec ./dispatch.ori;;
esac
