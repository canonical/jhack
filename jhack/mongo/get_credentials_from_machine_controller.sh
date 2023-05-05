#!/bin/bash

machine=${1:-0}
model=${2:-controller}

read -d '' -r cmds <<'EOF'
conf=/var/lib/juju/agents/machine-*/agent.conf
user=`sudo grep tag $conf | cut -d' ' -f2`
password=`sudo grep statepassword $conf | cut -d' ' -f2`
if [ -f /snap/bin/juju-db.mongo ]; then
  client=/snap/bin/juju-db.mongo
elif [ -f /usr/lib/juju/mongo*/bin/mongo ]; then
  client=/usr/lib/juju/mongo*/bin/mongo
else
  client=/usr/bin/mongo
fi
echo "$client" "$user" "$password"
EOF
juju ssh -m "${model}" "${machine}" "${cmds}"
