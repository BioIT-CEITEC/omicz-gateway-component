# Installing OmiCZ Gateway on a Linux server

Copy-and-paste guide for a fresh Linux server. Run the blocks in order.
For what each step does and how to configure instruments in the UI, see the [README](README.md).

---

## 1. Check which Linux you have

```bash
cat /etc/os-release
```

- `ID=ubuntu` or `ID=debian` → use section **2a**
- `ID=rhel`, `rocky`, `almalinux` or `centos` → use section **2b**

---

## 2a. Install git and Docker — Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

> **Debian:** replace `linux/ubuntu` with `linux/debian` in both URLs above.

---

## 2b. Install git and Docker — RHEL / Rocky / Alma / CentOS Stream

```bash
sudo dnf install -y git dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

> **CentOS Stream:** use `https://download.docker.com/linux/centos/docker-ce.repo` instead.
> If podman is preinstalled and conflicts: `sudo dnf remove -y podman buildah` first.

---

## 3. Start Docker and allow your user to use it

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

**Log out and log back in** so the group change takes effect.

> Members of the `docker` group effectively have root access on the server. Add only the account that runs the gateway.

---

## 4. Check the installation

```bash
git --version
docker --version
docker compose version        # must be 2.24 or newer
docker run --rm hello-world
```

---

## 5. Check the server before installing the app

**The instrument output folder must exist and be readable** (for a network share, it must already be mounted, e.g. via `/etc/fstab`):

```bash
ls /path/to/sequencer/output
```

If the folder does not exist when the app starts, Docker silently creates an empty one and the app sees no runs.

**The ports must be free** (no output = free):

```bash
sudo ss -ltnp | grep -E ':(5432|5672|15672|8000|8001|8090)\b'
```

If 5432 is taken (e.g. Postgres already runs on the server), see [Port 5432 already in use](#port-5432-already-in-use) below.

**SELinux** (RHEL / Rocky / Alma only):

```bash
getenforce
```

If it prints `Enforcing`, see [SELinux](#selinux) below.

---

## 6. Install the app

```bash
git clone https://github.com/BioIT-CEITEC/omicz-gateway-component.git
cd omicz-gateway-component

cp .env.example .env
cp backend/.env.example backend/.env
```

Edit `.env` — set the real path of the instrument output folder on this server:

```bash
nano .env
```
```env
MACHINE_1_PATH=/path/to/sequencer/output
```

Edit `backend/.env` — fill in the S3 values from the project administrator:

```bash
nano backend/.env
```
```env
S3_ENDPOINT=https://...
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET=...
S3_PREFIX=raw_run_data/
```

Build, start and create the database tables:

```bash
docker compose up -d --build
docker ps                     # all 8 containers should be "Up"
docker exec fastapi_gateway_backend alembic upgrade head
```

Check that the app can see the instrument folder:

```bash
docker exec fastapi_gateway_watcher ls /runs/machine-1
```

Open the UI at `http://<server-address>:8001` and continue with
[First-time configuration in the UI](README.md#first-time-configuration-in-the-ui).

---

## Security — read before exposing the server on a network

- The UI has **no login**.
- The backend and frontend containers have access to the Docker socket. Anyone who can reach ports **8000** or **8001** can control Docker on this server, which is equivalent to root access.
- RabbitMQ (`15672`, guest/guest) and Adminer (`8090`, postgres/postgres) use default passwords.
- **Docker bypasses ufw/firewalld rules** for published ports, so a host firewall alone does not protect them.

Keep the server on an internal network only. To make the internal services reachable only from the server itself, create `docker-compose.override.yml`:

```bash
cat > docker-compose.override.yml <<'EOF'
services:
  db:
    ports: !override ["127.0.0.1:5432:5432"]
  adminer:
    ports: !override ["127.0.0.1:8090:8080"]
  rabbitmq:
    ports: !override ["127.0.0.1:5672:5672", "127.0.0.1:15672:15672"]
  backend:
    ports: !override ["127.0.0.1:8000:8000"]
EOF
docker compose up -d
```

Only the UI (`8001`) then stays reachable from other machines.

---

## Troubleshooting

### Port 5432 already in use

Map the database to another host port in `docker-compose.override.yml` (merge with the security block above if you use it):

```yaml
services:
  db:
    ports: !override ["127.0.0.1:5433:5432"]
```

Then `docker compose up -d`. The app itself talks to the database inside Docker and needs no other change.

### SELinux

Docker CE does not enable SELinux labelling by default, so this usually works as is. If `docker logs` or `docker exec fastapi_gateway_watcher ls /runs/machine-1` shows `Permission denied`, allow the folders for containers:

```bash
sudo chcon -R -t container_file_t /path/to/sequencer/output
sudo chcon -R -t container_file_t ~/omicz-gateway-component
```

For network shares, mount them with the `context="system_u:object_r:container_file_t:s0"` option instead.

### Instrument folder on NFS with `root_squash`

The containers run as root. With `root_squash`, root may not be able to read the share — `docker exec fastapi_gateway_watcher ls /runs/machine-1` then fails. Ask the storage administrator to export the share readable for this server, or mount it with world-read permissions.

### File ownership in the repository

The containers run as root, so `logs/`, `backups/` and files pulled by **Settings → Update** become owned by root. Update the app through the UI; if you must run `git` by hand in this folder, use `sudo`.

### Logs

```bash
docker compose logs
docker logs fastapi_gateway_worker --tail 50
docker logs fastapi_gateway_watcher --tail 50
```
