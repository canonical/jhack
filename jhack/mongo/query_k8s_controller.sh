#!/bin/bash
set -x
kctl=${1}
user=${2}
password=${3}
k8s_ns=${4}
k8s_controller_pod=${5}
query=${6}
#${kctl} exec -n "${k8s_ns}" "${k8s_controller_pod}" -c mongodb -it -- bash -c "/bin/mongo 127.0.0.1:37017/juju --authenticationDatabase admin --quiet --ssl --sslAllowInvalidCertificates --username '${user}' --password '${password}' --help"
#${kctl} exec -n "${k8s_ns}" "${k8s_controller_pod}" -c mongodb -it -- bash -c "/bin/mongo 127.0.0.1:37017/juju --authenticationDatabase admin --quiet --tls --tlsAllowInvalidCertificates --username '${user}' --password '${password}' --eval '${query}'"
microk8s.kubectl exec -n "${k8s_ns}" "${k8s_controller_pod}" -c mongodb -t -- bash -c "/bin/mongo 127.0.0.1:37017/juju --authenticationDatabase admin --quiet --tls --tlsAllowInvalidCertificates --username ${user} --password ${password} --eval ${query}"
#${kctl} exec -n "${k8s_ns}" "${k8s_controller_pod}" -c mongodb -it -- bash -c "/bin/mongo 127.0.0.1:37017/juju --authenticationDatabase admin --quiet --tls --tlsAllowInvalidCertificates --username ${user} --password ${password}"
