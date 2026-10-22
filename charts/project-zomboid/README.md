# Project Zomboid Helm chart

Install from this local chart with Helm 3:

```bash
helm upgrade --install zomboid ./charts/project-zomboid -n zomboid \
  --create-namespace --set server.existingSecret.name=zomboid-admin
```

Create `zomboid-admin` in the same namespace first, with an `admin-password` key.
The chart refuses an omitted secret, duplicate game/direct UDP ports, a shutdown
grace period too short for the configured timeout, and invalid schema values.

The default creates two retained PVCs through a single-replica StatefulSet:
30 GiB for `/server`, 20 GiB for `/data`. Override
`persistence.server.existingClaim` / `persistence.data.existingClaim` to reuse
claims. The storage must be writable by UID/GID 10000.

| Setting | Default |
| --- | --- |
| `image.repository` | `ghcr.io/zhmarvi/project-zomboid` |
| `image.tag` / `image.pullPolicy` | `latest` / `Always` |
| `image.digest` | Empty; when set, overrides tag |
| `server.name` | `servertest`, persisted world/config identity |
| `server.existingSecret.name` / `.key` | Required name / `admin-password` |
| `server.steamBranch` | `public` |
| `server.updateOnStart` / `.validateOnUpdate` | `true` / `true` |
| `server.minMemory` / `.maxMemory` | `1g` / `4g` |
| `service.type` | `LoadBalancer` |
| `service.gamePort` / `.directPort` | `16261` / `16262` UDP |
| `service.externalTrafficPolicy` | `Local` |
| `hostNetwork` | `false` |
| `terminationGracePeriodSeconds` | `180` |

See `values.yaml` for resources, storage classes, annotations, scheduling and
supported `server.settings`. UID/GID, replica count, writable directory mounts,
and Linux/AMD64 scheduling are fixed intentionally.

If the pod has a 3.5 GB memory limit, override the default 4g Java heap too.
The example profile uses Kubernetes `3500M` (3.5 GB, decimal) for the limit.
From the repository root, apply both settings to your existing Helm release:

```bash
helm upgrade zomboid ./charts/project-zomboid -n YOUR_NAMESPACE \
  --reuse-values -f examples/values-3-5gb.yaml
```

The profile sets a 2g maximum heap and reserves the rest of the limit for JVM
native memory, threads, and game libraries. It is a starting point, not a
guarantee that a particular world or mod set will fit. A manual `kubectl edit`
limit can be replaced by the next Helm upgrade; keeping the limit in Helm values
prevents that. The profile also waits 900 seconds (15 minutes) before the first
readiness check, then checks every 30 seconds with a 10-second timeout. Set
`readinessProbe.initialDelaySeconds` in your Helm values to change that wait;
the chart's default is 10 seconds. A longer readiness delay leaves the pod
unready longer and does not stop a crashing container from restarting.

Confirm the previous exit reason and current memory use with:

```bash
kubectl get pod zomboid-project-zomboid-0 -n YOUR_NAMESPACE \
  -o jsonpath='{.status.containerStatuses[?(@.name=="server")].lastState.terminated.reason}{"\n"}'
kubectl top pod zomboid-project-zomboid-0 -n YOUR_NAMESPACE --containers
kubectl logs zomboid-project-zomboid-0 -n YOUR_NAMESPACE -c server --previous
```

Readiness probe failures only keep the Service from sending traffic; this chart
has no liveness probe, so they do not restart the container. A previous exit
reason of `OOMKilled` confirms the memory limit was exceeded. If it still ends
in `OOMKilled`, raise the limit if possible. The server's startup warnings about
missing icons or models are not themselves evidence of an out-of-memory failure.

For a dedicated bare-metal node:

```yaml
hostNetwork: true
service:
  type: ClusterIP
nodeSelector:
  kubernetes.io/hostname: YOUR_AMD64_NODE
```

Clients then connect to the node IP using UDP 16261; also allow UDP 16262.
Host networking may be prohibited by your cluster's Pod Security policy; the
default LoadBalancer mode does not need it.

`service.type=NodePort` defaults to node ports 30261/30262. NodePort translates
the internal game/direct ports, and game clients may still try an advertised
direct port. Configure and verify router/firewall mappings so external UDP
16261/16262 reach those two node ports respectively. A UDP LoadBalancer with
matching external/internal ports or host networking is simpler.

Changing a ConfigMap setting rolls the pod using a checksum annotation. Changing
an admin Secret does not rotate existing database credentials. Chart-created
PVCs survive uninstall; remove them manually only when you intend to lose data.
