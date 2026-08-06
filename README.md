# DroneMobile for Home Assistant

A HACS-compatible custom integration that connects Firstech/Compustar
DroneMobile vehicles to Home Assistant through the
[`drone_mobile`](https://pypi.org/project/drone-mobile/) Python package.

> [!WARNING]
> DroneMobile does not provide a supported public API. Remote vehicle commands
> can have real-world safety consequences. Test every entity carefully and add
> appropriate conditions to automations that start, stop, unlock, or otherwise
> control a vehicle.

## Features

Each vehicle is represented as one Home Assistant device with:

- an engine switch for remote start and stop;
- a door lock entity;
- running-state, battery-voltage, odometer, temperature, and update sensors
  when those values are supplied by DroneMobile;
- a GPS device tracker when location is available;
- buttons for trunk, panic, auxiliary outputs, location, and status requests;
- interactive SMS or authenticator-app MFA during setup;
- account-specific token storage inside Home Assistant's `.storage` directory.

Vehicle data is normally polled every two minutes. After a start, stop, lock,
or unlock command, the integration refreshes immediately. It only retries at
5, 15, and 30 seconds while DroneMobile still reports a state that does not
match the command. API calls run outside Home Assistant's event loop so a slow
cloud request does not block Home Assistant.

## Install with HACS

Add this repository to HACS as a custom repository:

1. Open HACS and choose **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Enter `https://github.com/jaredthejellyfish/drone-mobile-ha` and select
   **Integration**.
4. Download **DroneMobile** and restart Home Assistant.

For a manual installation, copy `custom_components/drone_mobile` into the
same path under your Home Assistant configuration directory, then restart.

## Configure

1. In Home Assistant, open **Settings → Devices & services**.
2. Choose **Add integration** and search for **DroneMobile**.
3. Enter the email address and password for your DroneMobile account.
4. If prompted, enter the SMS or authenticator-app verification code.

Credentials are stored in the Home Assistant config entry. Authentication
tokens and remembered-device data are stored under
`.storage/drone_mobile/<account-id>` with restrictive permissions.

## Development

The development environment targets Home Assistant 2026.8 on Python 3.14.2+.

```sh
uv sync
uv run ruff check custom_components tests
uv run pytest
```

The standalone package CLI remains available for troubleshooting:

```sh
drone-mobile-demo you@example.com list
```

Omit the password from the command so the CLI prompts without exposing it in
shell history or the process list.

## Project links

- [Documentation and source](https://github.com/jaredthejellyfish/drone-mobile-ha)
- [Issue tracker](https://github.com/jaredthejellyfish/drone-mobile-ha/issues)
- [DroneMobile Python package](https://pypi.org/project/drone-mobile/)

## Disclaimer

This project is unofficial and is not affiliated with or endorsed by
DroneMobile, Firstech, or Compustar. The underlying API can change without
notice.
