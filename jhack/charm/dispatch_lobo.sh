#!/bin/sh

# template filled in by jhack
DISABLED={%DISABLED%}
EXIT_CODE={%EXIT_CODE%}

# special case: full lobotomy
if [ "$DISABLED" = "ALL" ]
then
  juju-log full lobotomy ACTIVE: event "${JUJU_DISPATCH_PATH}" ignored.
  exit $EXIT_CODE
fi

case ",$JUJU_DISPATCH_PATH," in
  (*,"$DISABLED",*)
   juju-log selective lobotomy ACTIVE: event "${JUJU_DISPATCH_PATH}" ignored.
   exit $EXIT_CODE
   ;;
  (*) exec ./dispatch.ori
  ;;
esac
