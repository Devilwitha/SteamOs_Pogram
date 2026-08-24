#!/bin/bash
# Mount-Helfer fuer 61-usb-automount.rules (siehe dort) - wird von udev als
# root beim Einstecken/Entfernen einer USB-Speicher-Partition (oder eines
# partitionslos formatierten USB-Sticks) aufgerufen.
#
# Nutzt bewusst rohes mount(8)/umount(8) statt udisksctl: dadurch
# unabhaengig von einer laufenden grafischen Sitzung oder einer aktiven
# D-Bus-/Polkit-Session (udisks2' "allow_active"-Regel greift nur innerhalb
# einer von logind als aktiv erkannten Sitzung - ein per systemd --user
# +Linger laufender Dienst zaehlt dafuer nicht zuverlaessig). Ein direkt von
# udev/root ausgefuehrtes Skript kennt dieses Problem nicht und funktioniert
# deshalb identisch im Desktop- wie im Game Mode (siehe steamOs/README.md,
# Abschnitt "USB-Automount").
#
# USER/UID/GID werden nicht hier ermittelt, sondern von der udev-Regel als
# Argumente mitgegeben (dort von install.sh per sed eingetragen) - ein per
# udev/root gestartetes Skript kann den eingeloggten Desktop-Benutzer sonst
# nicht zuverlaessig selbst bestimmen.
set -u

ACTION="$1"       # add | remove
DEVNAME="$2"      # Kernel-Name, z. B. sda1 (udev %k)
TARGET_USER="$3"
TARGET_UID="$4"
TARGET_GID="$5"

DEV="/dev/$DEVNAME"
MP="/run/media/$TARGET_USER/$DEVNAME"

log() { logger -t usb-automount "$DEVNAME: $*"; }

case "$ACTION" in
add)
    [ -b "$DEV" ] || exit 0
    if mountpoint -q "$MP" 2>/dev/null; then
        log "bereits gemountet unter $MP"
        exit 0
    fi

    FSTYPE=$(blkid -s TYPE -o value "$DEV" 2>/dev/null || true)
    if [ -z "$FSTYPE" ]; then
        log "kein Dateisystem erkannt, ueberspringe"
        exit 0
    fi

    OPTS="rw,nosuid,nodev,noatime"
    case "$FSTYPE" in
        vfat|exfat)
            OPTS="$OPTS,uid=$TARGET_UID,gid=$TARGET_GID,utf8,umask=000,flush"
            ;;
        ntfs)
            # ntfs3 ist der im Kernel eingebaute Treiber (kein FUSE/
            # ntfs-3g-Paket noetig, auf SteamOS/Bazzite-Kerneln vorhanden).
            FSTYPE="ntfs3"
            OPTS="$OPTS,uid=$TARGET_UID,gid=$TARGET_GID,windows_names"
            ;;
        ext2|ext3|ext4|btrfs|xfs|f2fs)
            : # native Linux-Dateisysteme: Rechte kommen vom Dateisystem selbst
            ;;
        *)
            log "unbekannter Dateisystemtyp $FSTYPE, versuche Standardmount trotzdem"
            ;;
    esac

    mkdir -p "$MP"
    if mount -t "$FSTYPE" -o "$OPTS" "$DEV" "$MP" 2>>/run/usb-automount.log; then
        log "gemountet unter $MP ($FSTYPE)"
    else
        log "Mount fehlgeschlagen (Details: /run/usb-automount.log)"
        rmdir "$MP" 2>/dev/null || true
    fi
    ;;
remove)
    if mountpoint -q "$MP" 2>/dev/null; then
        # Geraet ist beim "remove"-Event physisch bereits weg - ein
        # regulaerer umount kann daher fehlschlagen (Sync auf ein
        # verschwundenes Blockgeraet). -l (lazy) raeumt den Mountpoint
        # trotzdem aus dem Namensraum, sobald er nicht mehr busy ist.
        umount "$MP" 2>/dev/null || umount -l "$MP" 2>/dev/null || true
        log "ausgehaengt"
    fi
    rmdir "$MP" 2>/dev/null || true
    ;;
esac
