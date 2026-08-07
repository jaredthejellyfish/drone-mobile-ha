# DroneMobile Integration Improvements

Reviewed against the current working tree on August 6, 2026. The existing
suite passes (`14 passed`), and Ruff lint and format checks pass. The items
below are runtime, safety, and coverage gaps that those checks do not catch.

## High priority

<!-- ### 1. Force credential validation to use the submitted password

**Evidence:** `custom_components/drone_mobile/config_flow.py:49-61`,
`custom_components/drone_mobile/api.py:22-34`, and
`custom_components/drone_mobile/manifest.json:11`.

`_validate_credentials()` creates a client in the account's persistent token
directory and calls `get_vehicles()`. In the pinned `drone_mobile` 0.4.1
client, that call loads a still-valid token before attempting password
authentication. Setup after deleting an old entry, or a reauthentication
attempt while a cached token remains valid, can therefore accept an incorrect
new password and store it in the config entry. The failure remains hidden until
the cached token can no longer be refreshed.

**Improvement:** add a supported `validate_credentials`/forced-login operation
to the library and use it from the flow. Validation should authenticate with
the submitted password without destroying a known-good runtime token when
validation fails. Add setup and reauthentication tests proving that a wrong
password is rejected even when valid cached tokens exist. -->

<!-- ### 2. Preserve the MFA challenge session between config-flow steps

**Evidence:** `custom_components/drone_mobile/config_flow.py:49-61`,
`custom_components/drone_mobile/config_flow.py:80-86`, and
`custom_components/drone_mobile/config_flow.py:113-138`.

The first validation creates and closes a client after `MFARequiredError`.
Submitting the MFA form creates another client and starts authentication again,
so it responds with the user-entered code against a newly created Cognito
challenge session. This is especially fragile for SMS MFA because the second
authentication can issue a second code after the user has already entered the
first one.

**Improvement:** extend the API library so authentication can return a pending
challenge object/session and later resume that exact challenge with the code.
Keep that pending challenge only in config-flow memory, close it on abort, and
cover SMS MFA, authenticator MFA, wrong codes, expired codes, and retries with
Home Assistant config-flow tests. -->

<!-- ### 3. Add entities when vehicles or data become available after startup

**Evidence:** `custom_components/drone_mobile/sensor.py:88-100`,
`custom_components/drone_mobile/device_tracker.py:15-26`, and the one-time
entity creation in `binary_sensor.py:14-24`, `button.py:69-80`,
`lock.py:14-23`, and `switch.py:14-24`.

Platforms create entities only from the first coordinator snapshot. A tracker
or optional sensor whose value is `None` during setup is omitted permanently,
even if later refreshes provide the value. Vehicles added to the DroneMobile
account after Home Assistant starts also never receive entities until the
config entry is reloaded.

**Improvement:** register a coordinator listener in each platform that adds
entities for newly seen vehicle IDs and newly supported data keys while
tracking already-added unique IDs. A simpler safe first step is to create the
tracker and sensors that the pinned library can actually populate for every
initial vehicle, and let temporarily unavailable values report `unknown`.
Remove or reserve battery-percentage and fuel-level definitions until the
library can produce those values. Add tests for a missing initial location
that appears later and for a vehicle added after setup. -->

<!-- ### 4. Scope entity and device identifiers to an account

**Evidence:** `custom_components/drone_mobile/config_flow.py:69-72` and
`custom_components/drone_mobile/entity.py:19-28,40-52`.

The config flow permits multiple accounts, but entity unique IDs and device
identifiers contain only the vehicle ID. If the same physical vehicle is shared
across two DroneMobile accounts, or if the API's vehicle IDs are not globally
unique, the second entry's entities collide in Home Assistant's entity registry
and its vehicle device can merge with the first account's device.

**Improvement:** decide explicitly whether shared vehicles should be
deduplicated across accounts. If each config entry should remain independent,
prefix both entity unique IDs and device identifiers with a stable,
privacy-safe account identifier. Add a two-entry test where both accounts
return the same vehicle ID and verify deterministic registry behavior. -->

## Medium priority

<!-- ### 5. Serialize access to the shared blocking client

**Evidence:** `custom_components/drone_mobile/coordinator.py:150-201`,
`custom_components/drone_mobile/coordinator.py:257-275`, and
`custom_components/drone_mobile/coordinator.py:277-344`.

Coordinator polling, scheduled GPS requests, and user commands all submit work
to executor threads against the same `DroneMobileClient`. The pinned client
uses one `requests.Session`, and concurrent access to a session is not
guaranteed to be thread-safe. A timer and a command can also race token refresh
or shutdown.

**Improvement:** serialize all client calls with one coordinator-owned
`asyncio.Lock`, or move to a library client that explicitly supports concurrent
async use. Ensure unload waits for tracked in-flight client work before closing
the client. Test an overlapping refresh, location request, and command. -->

### 6. Make active GPS polling configurable and rate-limit aware

**Evidence:** `custom_components/drone_mobile/__init__.py:29-32`,
`custom_components/drone_mobile/const.py:11-15`, and
`custom_components/drone_mobile/coordinator.py:110-201`.

Every entry automatically sends active location commands every five minutes
while running and every thirty minutes while parked. This is more than passive
cloud polling: it can consume API quota, wake vehicle hardware, and continuously
refresh sensitive location data. Failures only log and retry on the fixed
schedule, including rate-limit responses.

**Improvement:** add an options flow to enable/disable active GPS requests and
configure conservative running/parked intervals. Apply exponential backoff or
honor a server retry interval after rate limiting, and expose the behavior
clearly during setup as well as in the README.

### 7. Remove the integration's mutation of a dependency global

**Evidence:** `custom_components/drone_mobile/coordinator.py:63-76`.

`_request_location()` mutates `drone_mobile.const.AVAILABLE_COMMANDS` and sends
the undocumented `A30` controller command because the library's public
`get_location()` path is known not to work. This process-wide mutation couples
the integration to an internal implementation detail and can silently break on
a dependency update.

**Improvement:** fix the location command in `drone_mobile`, expose it through a
stable public method, release that version, and remove `LOCATION_COMMAND`,
`AVAILABLE_COMMANDS.add()`, and the raw `send_command()` call from the
integration. Retain a contract test for command and device type.

### 8. Close the client if platform setup fails

**Evidence:** `custom_components/drone_mobile/__init__.py:14-32`.

The cleanup `try` covers only the first coordinator refresh. If forwarding one
of the six platforms raises, setup exits without shutting down the coordinator
or closing its HTTP session.

**Improvement:** include runtime-data assignment and platform forwarding in
lifecycle-safe cleanup. On any setup failure after client creation, shut down
the coordinator and close the client before re-raising. Add a test where a
platform setup fails.

### 9. Log unexpected config-flow exceptions

**Evidence:** `custom_components/drone_mobile/config_flow.py:87-94`,
`custom_components/drone_mobile/config_flow.py:129-136`, and
`custom_components/drone_mobile/config_flow.py:181-188`.

Each flow maps every unexpected `Exception` to `unknown` without logging it,
even though the UI tells the user to check the logs. Programming errors and
upstream response-shape changes are therefore hidden.

**Improvement:** keep specific user-facing mappings for expected API errors,
but log unexpected exceptions with a traceback before returning `unknown`.
Test the expected error mappings rather than the broad fallback.

### 10. Avoid enabling every remote command for every vehicle by default

**Evidence:** `custom_components/drone_mobile/button.py:23-66`,
`custom_components/drone_mobile/lock.py:14-46`, and
`custom_components/drone_mobile/switch.py:14-48`.

All vehicles receive trunk, panic, auxiliary, lock, and remote-start controls
without a capability check. Unsupported controls create predictable failures,
and rarely used safety-sensitive buttons such as panic and auxiliary outputs
are enabled by default.

**Improvement:** use vehicle capability data when the API exposes it. Until
then, disable optional/destructive buttons by default in the entity registry
and document how to enable only the controls supported by a vehicle.

## Lower priority and project quality

### 11. Do not assign every discovered vehicle to `Garage`

**Evidence:** `custom_components/drone_mobile/entity.py:40-52`.

`suggested_area="Garage"` can place every new vehicle device into an area that
may not exist or may be incorrect, particularly for multiple vehicles.

**Improvement:** omit `suggested_area` unless the integration has reliable
location-derived evidence for an area. Let the user choose the device area.

### 12. Exercise the integration through Home Assistant's test harness

**Evidence:** `tests/test_config_flow.py:1-23`,
`tests/test_entities.py:33-154`, and the absence of coordinator/lifecycle
integration tests.

The current tests call flow methods with `asyncio.run()` and use partial mocks,
so they do not verify config entries, platform forwarding, entity registration,
coordinator refresh behavior, reauthentication, unload cleanup, or scheduled
callbacks inside Home Assistant. There is also no checked-in CI workflow, so
the passing local suite is not enforced for pull requests.

**Improvement:** adopt the Home Assistant pytest fixtures, mock the library at
the integration boundary, and add end-to-end tests for setup, reauth, MFA,
commands, dynamic entities, update failure/recovery, and unload. Run pytest,
Ruff lint, and Ruff format checks in CI. For the staged GPS scheduler,
specifically verify setup wiring, idempotent timer registration, multiple
vehicles, accepted and rejected requests, start/request-location command paths,
delayed-refresh coalescing, and timer cancellation during unload.

### 13. Use one release version source

**Evidence:** `pyproject.toml:1-9`,
`custom_components/drone_mobile/manifest.json:11-12`, and
`tests/test_structure.py:15-27`.

The project version is `0.1.0` while the HACS manifest version is `0.1.5`, and a
test hard-codes the manifest value. This makes release drift easy and requires
test edits for every release without validating compatibility.

**Improvement:** define which file owns the release version and have release
automation synchronize or verify the other metadata. Test version format and
consistency rather than one specific release number.

### 14. Add semantic metadata for the running-state binary sensor

**Evidence:** `custom_components/drone_mobile/binary_sensor.py:27-40`.

The running sensor has an icon but no `BinarySensorDeviceClass.RUNNING`, so
Home Assistant cannot apply its standard semantics and presentation.

**Improvement:** set the running device class and add a small entity-description
test.

### 15. Declare and test the minimum supported Home Assistant version

**Evidence:** `pyproject.toml:6-16`, `README.md:62-70`, and `hacs.json:1-4`.

Development is pinned to Home Assistant 2026.8 and Python 3.14.2+, but HACS
metadata does not tell users which Home Assistant releases are supported.
Older installations can therefore install the integration even though they
are not covered by this repository's tests.

**Improvement:** determine the oldest Home Assistant release the integration
intends to support, test against it, declare that minimum in HACS metadata, and
keep the README's compatibility statement aligned with CI.

