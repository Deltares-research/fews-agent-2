# Deploy the FEWS agent to an Azure GPU VM

Quick-n-dirty, self-hosted: one GPU VM runs a single container that bundles
**Ollama + the Streamlit chat UI** (`Dockerfile.bundled`). You build it on the
box and run it. No Azure OpenAI, no registry, no Kubernetes.

The first run pulls the ~4.7 GB model — a **one-time** ~5–8 min cost. After
that the VM is a server: stop/start is ~1–2 min, redeploying code is seconds.

## Security model — who can access it

**The app has no login of its own.** Access is controlled by Azure, not by
the app:

- The Streamlit port is **never exposed to the internet**. The container binds
  `127.0.0.1:8501` on the VM, and no firewall rule opens 8501.
- Colleagues reach the UI only by tunneling over an **Entra-ID-authenticated
  SSH session** (`az ssh`). So **access == having Azure RBAC on this VM** —
  i.e. Deltares colleagues with Azure access whom you've granted a role.
- Each person uses their own Azure identity (no shared keys / passwords).
  Revoke someone by removing their role assignment.

If you'd rather eliminate the public IP entirely, see "Zero public surface
(Bastion)" at the end.

---

## 0. Prerequisites (confirm on the Deltares subscription)

- `az` CLI installed locally + `az login` done.
- **GPU quota:** *Standard NCASv3 Family vCPUs ≥ 4* in your region:
  ```powershell
  az vm list-usage --location westeurope --query "[?contains(localName,'NCAS')]" -o table
  ```
  If it's `0`, request an increase (may need Deltares IT) — or use the CPU
  fallback at the bottom while you wait.
- **Permission to grant RBAC** on the VM (Owner / User Access Administrator)
  so you can add colleagues' "Virtual Machine User Login" roles.
- Any **mandatory tags** your subscription policy requires (`--tags ...`).

Set your values once:

```powershell
$RG   = "fews-agent-rg"
$LOC  = "westeurope"
$VM   = "fews-agent-vm"
$USER = "azureuser"
az account set --subscription "<deltares-subscription-id>"
```

---

## 1. Create the GPU VM (drivers + Docker preinstalled, Entra SSH login)

`microsoft-dsvm:ubuntu-hpc` ships with the NVIDIA driver + container toolkit
already set up. `--assign-identity` + the AAD extension enable per-user Entra
login. SSH (22) is restricted to your IP; **8501 is never opened.**

```powershell
az group create -n $RG -l $LOC

az vm create -g $RG -n $VM `
    --image microsoft-dsvm:ubuntu-hpc:2204:latest `
    --size Standard_NC4as_T4_v3 `
    --admin-username $USER `
    --generate-ssh-keys `
    --assign-identity `
    --public-ip-sku Standard

# Entra ID SSH login (so colleagues sign in with their Deltares Azure account)
az vm extension set -g $RG --vm-name $VM `
    --name AADSSHLoginForLinux --publisher Microsoft.Azure.ActiveDirectory

# Lock SSH (22) to YOUR ip; do NOT open 8501 anywhere.
$MYIP = (Invoke-RestMethod https://api.ipify.org)
az network nsg rule update -g $RG --nsg-name "$($VM)NSG" -n default-allow-ssh `
    --source-address-prefixes "$MYIP/32"

$IP    = az vm show -d -g $RG -n $VM --query publicIps -o tsv
$VMID  = az vm show -g $RG -n $VM --query id -o tsv
```

### Grant access (you, then each colleague)

```powershell
# You: admin login (lets you sudo to build/run)
$ME = az ad signed-in-user show --query id -o tsv
az role assignment create --role "Virtual Machine Administrator Login" `
    --assignee $ME --scope $VMID

# Each colleague: user login (enough to tunnel; no sudo)
az role assignment create --role "Virtual Machine User Login" `
    --assignee "colleague@deltares.nl" --scope $VMID
```

> Colleagues also need the SSH port reachable from their network. If they're
> on different IPs, either add their IPs/Deltares egress CIDRs to the
> `default-allow-ssh` rule, or use the Bastion option (no public IP at all).

---

## 2. Build + run on the VM (you, once)

```powershell
az ssh vm -g $RG -n $VM
```

Inside the VM:

```bash
# ubuntu-hpc has the NVIDIA runtime; ensure docker is present + GPU-wired:
docker --version || (curl -fsSL https://get.docker.com | sudo sh)
sudo nvidia-ctk runtime configure --runtime=docker 2>/dev/null; sudo systemctl restart docker

git clone https://github.com/amavrits/fews-agent-2.git
cd fews-agent-2
sudo docker build -f Dockerfile.bundled -t fews-agent .

# Bind to the VM's localhost ONLY (127.0.0.1) — not reachable from the internet,
# only through the SSH tunnel. --gpus all = GPU; volume persists the model.
sudo docker run -d --gpus all -p 127.0.0.1:8501:8501 \
    -v ollama-models:/root/.ollama \
    --restart unless-stopped \
    --name fews fews-agent

sudo docker logs -f fews   # wait for the model pull + Streamlit startup
```

---

## 3. How colleagues connect

Anyone you granted a role runs (from their own machine, signed into Azure):

```bash
az login
az ssh vm -g fews-agent-rg -n fews-agent-vm -- -L 8501:localhost:8501
# then open http://localhost:8501 in their browser
```

The `-L 8501:localhost:8501` forwards their local 8501 to the VM's
`127.0.0.1:8501`. No public app port, no shared secret — their Azure identity
is the credential.

---

## Everyday operations

```bash
# Terminal inside the running container (Ollama already serving):
sudo docker exec -it fews bash       #  -> streamlit run frontend/web_app.py, etc.

# Redeploy new code (seconds):
cd fews-agent-2 && git pull
sudo docker build -f Dockerfile.bundled -t fews-agent .
sudo docker rm -f fews
sudo docker run -d --gpus all -p 127.0.0.1:8501:8501 -v ollama-models:/root/.ollama \
    --restart unless-stopped --name fews fews-agent
```

```powershell
# Stop billing when idle (model stays on disk; restart ~1-2 min):
az vm deallocate -g $RG -n $VM
az vm start      -g $RG -n $VM

# Revoke a colleague:
az role assignment delete --role "Virtual Machine User Login" `
    --assignee "colleague@deltares.nl" --scope $VMID
```

---

## CPU fallback (no GPU quota yet)

Same flow, CPU VM, drop `--gpus all`. Inference ~10–45 s/turn — slow but
unblocks a demo.

```powershell
az vm create -g $RG -n $VM --image Ubuntu2204 --size Standard_D8s_v5 `
    --admin-username $USER --generate-ssh-keys --assign-identity --public-ip-sku Standard
# extension + RBAC + SSH-lock as in step 1; in the VM build as above and run:
# sudo docker run -d -p 127.0.0.1:8501:8501 -v ollama-models:/root/.ollama \
#     --restart unless-stopped --name fews fews-agent
```

## Zero public surface (Bastion)

Most locked-down: create the VM with **no public IP**, add Azure Bastion to
the VNet, and tunnel through it. Access stays Azure-RBAC-gated and nothing is
exposed to the internet.

```powershell
# (VM created without --public-ip-sku; Bastion deployed on the VNet)
az network bastion tunnel --name <bastion> -g $RG `
    --target-resource-id $VMID --resource-port 22 --port 2222
# in another shell:  ssh -L 8501:localhost:8501 $USER@localhost -p 2222
```

Bastion adds cost (~$140/mo Standard; cheaper Developer SKU exists) — worth it
for a long-lived internal tool, overkill for a short demo.
