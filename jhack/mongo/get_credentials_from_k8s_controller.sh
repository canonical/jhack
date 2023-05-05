#!/bin/bash
kubectl_bin=microk8s.kubectl
k8s_ns=`juju whoami | grep Controller | awk '{print "controller-"$2}'`
k8s_controller_pod=`${kubectl_bin} -n ${k8s_ns} get pods | grep -E "^controller-([0-9]+)" | awk '{print $1}'`
mongo_user=`${kubectl_bin} exec -n ${k8s_ns} ${k8s_controller_pod} -c api-server -it -- bash -c "grep tag /var/lib/juju/agents/controller-*/agent.conf | cut -d' ' -f2 | tr -d '\n'"`
mongo_pass=`${kubectl_bin} exec -n ${k8s_ns} ${k8s_controller_pod} -c api-server -it -- bash -c "grep statepassword /var/lib/juju/agents/controller-*/agent.conf | cut -d' ' -f2 | tr -d '\n'"`

echo "$k8s_ns" "$k8s_controller_pod" --password "$mongo_pass" --username "$mongo_user"
