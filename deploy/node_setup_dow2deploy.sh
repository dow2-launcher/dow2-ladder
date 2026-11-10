#!/bin/bash
# node_setup.sh "<public key line>" - этап 1 прав доступа (10.11.2026), запускать под root на игровом узле.
# Заводит системного пользователя dow2deploy: пароль заблокирован, ключ rts только с from=<IP rts>,
# запись только в /srv/dow2battle, чтение логов dow2battle/udpgw (ACL --x на /var/lib/private + группа systemd-journal),
# sudo ТОЛЬКО systemctl restart|status игровых служб узла. Root-ключи и sshd здесь НЕ трогаются.
# Повторный запуск безопасен. Откат: userdel -r dow2deploy; rm /etc/sudoers.d/dow2deploy;
# setfacl -x u:dow2deploy /var/lib/private; chown -R root:root /srv/dow2battle.
set -eu
RTS_IP=37.27.234.236
PUB=${1:?public key line}
case "$PUB" in ssh-ed25519\ *) ;; *) echo "bad key"; exit 1;; esac
need=""; command -v sudo >/dev/null || need="$need sudo"; command -v setfacl >/dev/null || need="$need acl"
if [ -n "$need" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -q $need >/dev/null 2>&1 || { apt-get update -q >/dev/null; apt-get install -y -q $need >/dev/null; }
fi
id dow2deploy >/dev/null 2>&1 || useradd --system --user-group --create-home --home-dir /home/dow2deploy --shell /bin/bash dow2deploy
usermod -L dow2deploy 2>/dev/null || true
getent group systemd-journal >/dev/null && usermod -aG systemd-journal dow2deploy
install -d -m 700 -o dow2deploy -g dow2deploy /home/dow2deploy/.ssh
echo "from=\"$RTS_IP\",no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty $PUB" > /home/dow2deploy/.ssh/authorized_keys
chown dow2deploy:dow2deploy /home/dow2deploy/.ssh/authorized_keys; chmod 600 /home/dow2deploy/.ssh/authorized_keys
# код игровых служб: владелец dow2deploy (службы читают его как 644, писать им не нужно)
chown -R dow2deploy:dow2deploy /srv/dow2battle
# логи: StateDirectory у DynamicUser лежит в /var/lib/private (0700 root) - даём только проход
setfacl -m u:dow2deploy:--x /var/lib/private
# sudoers: только restart|status служб, которые есть на этом узле
units=""; for u in dow2-battle dow2-udpgw dow2-lobbymirror; do systemctl cat $u.service >/dev/null 2>&1 && units="$units $u"; done
cmds=""
add() { cmds="$cmds${cmds:+, }/usr/bin/systemctl $1, /bin/systemctl $1"; }
for u in $units; do add "restart $u"; add "status $u"; add "status $u --no-pager"; done
echo " $units " | grep -q " dow2-battle " && echo " $units " | grep -q " dow2-udpgw " && add "restart dow2-battle dow2-udpgw"
T=/etc/sudoers.d/.dow2deploy.new
{ echo "# этап 1 прав доступа 10.11.2026: rts выкладывает код и перезапускает только игровые службы"
  echo "Cmnd_Alias DOW2DEPLOY_CMDS = $cmds"
  echo "dow2deploy ALL=(root) NOPASSWD: DOW2DEPLOY_CMDS"; } > $T
chmod 440 $T
visudo -cf $T >/dev/null && mv $T /etc/sudoers.d/dow2deploy && visudo -c >/dev/null && echo "SUDOERS OK:$units"
echo "SETUP OK $(hostname)"
