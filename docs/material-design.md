# Final Qt application redesign

The Qt application uses a Material 3 inspired design across device management, vehicle controls, camera/replay, browsers, vehicle services, diagnostics and About. Version 0.5.0 removes the upper-left wordmark in both wide and compact layouts. The firmware UI remains supplied by the user’s image; QEMU feature parity is tracked separately in [virtual desktop validation](virtual-desktop.md).

The firmware-rendered Tesla UI remains a separate artifact. This redesign covers the host application, including device management, launch modes, vehicle controls, camera/replay, browsers, vehicle services, diagnostics, settings and About.

## Design direction

Use Material 3's semantic color roles, tonal surfaces, rounded controls, clear type hierarchy and selection indicators. Implement these using native Qt widgets and painting. Do not introduce a browser wrapper for the desktop shell.

- Provide light, dark and system appearance. Persist the user's selection and accent color. Accent personalization must preserve foreground/background contrast across all states.
- Centralize surface, container, primary, secondary, error, outline and corresponding foreground roles. Remove scattered fixed colors from the application stylesheet, banners, metrics and custom painters.
- Use an adaptive navigation rail with clear labels, selected indicators and keyboard focus. Consolidate duplicated navigation and contextual actions where appropriate.
- Use a coherent card hierarchy, filled primary actions, tonal secondary actions, outlined fields, switches, sliders, segmented selections, tabs, chips, dialogs and progress indicators across every page.
- Distinguish errors, warnings, pending operations and informational messages through text and icons as well as color. Keep technical logs in Diagnostics; summarize actionable outcomes in the workflow.
- Preserve accessible names, focus traversal, shortcuts, long-press behavior and immediate release/cancel semantics on driving controls. Animation must not delay control commands or repeat a released input.
- Support long labels, display scaling and smaller windows without clipped actions or unreadable information.

## Page coverage

| Area | Required result |
| --- | --- |
| Application shell | Consistent navigation, app bar, appearance/language settings and contextual actions. |
| Device manager | Firmware library, import, search, environment setup, native/QEMU mode selection, clear compatibility and boot state. |
| Session view | Layout appropriate to actual single/dual screens, actual previews, launch/stop/restart and active mode. |
| Controls | Gear, brake, accelerator, speed, steering, indicators and steering-wheel buttons with readable grouping and reliable hold/release. |
| Camera and replay | Source selection, playback timeline, feed status, telemetry and clear disconnected/error states. |
| Browsers | Normal/card/theater selection, URL controls and per-view status. |
| Vehicle services | Consistent climate/body/lights/energy/media controls and explicit availability. |
| Diagnostics | Readable stage-by-stage checks, filters, logs, export and QEMU progress without false desktop-success claims. |
| About/settings | Matching typography and surfaces, version/license information, language and appearance preferences. |

## Completion evidence

The redesign is complete only after implementation and visual review of all pages in both languages and light/dark appearance. Review populated, empty, loading, disabled, error and running states. Capture real native Qt screenshots on Windows/WSL and Linux, verify scaling and keyboard use, and re-test essential actions against the actual backend. A new stylesheet or one attractive device page alone is insufficient.

Final README screenshots must show the delivered application and verified firmware behavior; do not use mockups as evidence that QEMU or firmware features work.

## References

- [Material 3](https://m3.material.io/)
- [Official Material color theming and semantic roles](https://github.com/material-components/material-components-android/blob/master/docs/theming/Color.md)
- [Official navigation rail guidance](https://github.com/material-components/material-components-android/blob/master/docs/components/NavigationRail.md)

## Implemented and verified in this revision

`theme.py` owns curated semantic palettes, Qt styles and system appearance. `material_widgets.py` supplies a native checkbox-compatible switch. Appearance changes update widgets in place. The application uses a compact navigation rail below 1220 logical pixels and keeps preferences reachable from its menu. Existing long-press and replay input handlers remain in use.

- Captured all seven pages in light/dark appearance on Windows Qt and Debian WSLg.
- Checked 960 × 680 compact layout and 1360 × 920 desktop layout. Pages scroll vertically where needed.
- Verified contrast of normal text role pairs at 4.5:1 or greater for all three accents in both modes.
- Verified saved appearance, preservation of browser/service drafts and controls, native switch keyboard input, and cancellation of panel polling when closed.
- README captures are actual stopped-session Qt windows. QEMU mode selection and running-session screenshots are included in the virtual desktop guide. This design does not establish feature parity for QEMU.

Current release checks are recorded in [VALIDATION.md](VALIDATION.md).
