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
