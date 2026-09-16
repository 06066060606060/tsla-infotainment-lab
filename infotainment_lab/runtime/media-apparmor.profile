# Local compatibility labels for the firmware's peer-credential checks.
# Firmware binaries run from a read-only user mount, so these profiles retain
# the permissions of the desktop user while providing the expected peer name.

profile /usr/tesla/UI/bin/SpotifyServer flags=(attach_disconnected,mediate_deleted) {
  capability,
  network,
  unix,
  dbus,
  signal,
  ptrace,
  /** rwkmlix,
}

profile /usr/tesla/UI/bin/ChromiumAdapter flags=(attach_disconnected,mediate_deleted) {
  capability,
  network,
  unix,
  dbus,
  signal,
  ptrace,
  /** rwkmlix,
}

profile /usr/tesla/UI/bin/QtCar flags=(attach_disconnected,mediate_deleted) {
  capability,
  network,
  unix,
  dbus,
  signal,
  ptrace,
  /** rwkmlix,
}

profile /usr/tesla/UI/bin/QtCarCluster flags=(attach_disconnected,mediate_deleted) {
  capability,
  network,
  unix,
  dbus,
  signal,
  ptrace,
  /** rwkmlix,
}
