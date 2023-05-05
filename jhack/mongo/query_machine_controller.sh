#!/bin/bash
client=${1}
user=${2}
password=${3}
controller=${4}
machine=${5}
query=${6}
juju ssh -m "$controller" "$machine" -- "$client" '127.0.0.1:37017/juju' --authenticationDatabase admin --tls --tlsAllowInvalidCertificates --quiet --username "$user" --password "$password" --eval "$query"
