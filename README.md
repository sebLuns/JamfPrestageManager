# JamfPrestageManager
A better way to move devices between Jamf prestages.

PrestageManager is a command-line tool meant to streamline the process of moving computers and mobile devices between Prestages in Jamf.

It provides a number of advantages over the official MUT provided by Jamf:

* **Multi-Prestage Support:** In MUT, using a list of serial devices that are scoped to multiple prestages would fail. PrestageManager maps out all devices and their scoped prestages, allowing it to move devices in bulk across multiple prestages into the target prestage without the need to run it in "Classic" mode and procedurally moving through all prestage IDs.
* **Error Handling/Mitigation:** If an API token is invalidated during the operation, PrestageManager will attempt to generate a new one to seamlessly continue the process. Additionally, any device serial numbers that are incorrect or corrupted will be removed from the transfer queue before attempting to move the devices again.
* **Unified Error Logging:** It's not unusual for MUT to issue multiple error logs that can't be recovered if multiple operations are performed during the session. PrestageManager mitigates this by committing all errors to a single log that can be output after all operations are completed. Common errors are accompanied by readable explanations of the errors.

## Usage

*Prestage manager requires the `requests` package to be installed. You can install it by running `pip3 install requests`.*

PrestageManager can be run simply by calling it from a terminal:

`python3 prestagemanager.py`

Additional arguments can be used to set configuration options. 

* `--help`               Show all command-line options for configuration.
* `--url URL`            Your Jamf Instance URL, ex. "https://yourinstance.jamfcloud.com"
* `--username USERNAME`  Your Jamf login username
* `--targetid ID`        The ID of the prestage you want devices in your CSV to move to. Use `0` to use the Default prestage in Jamf, or `-1` to unassign devices.
* `--targetname NAME`    The name of the prestage you want devices in your CSV to move to. Overrides `--targetid`.
* `--file FILE`          CSV file of device serials (without header) that you wish to process.
* `--computer`           Use Computer Prestages
* `--mobile`             Use Mobile Device Prestages
* `--append`             Append all devices in CSV to a prestage
* `--exact`              Move any devices not in CSV out of the target prestage.
* `--defaultid ID`       *Exact mode only:* The ID of the prestage you want all extra devices to be moved to. Use `0` to use the Default prestage in Jamf, or `-1` to leave devices unassigned.
* `--defaultname NAME`   *Exact mode only:* The name of the prestage you want all extra devices to be moved to. Overrides `--defaultid`.
* `--bulk`               Move devices in bulk groups.
* `--granular`           Move devices one at a time (NOT RECOMMENDED).

An interactive flow will be automatically called to configure any required settings that weren't already set during the initial program call.

Additionally, there is a section within the code (`USER-DEFINED DEFAULTS`) that can be used to set certain variables that allow the user to skip having to set them up every time using the interactive flow or terminal arguments. Calling command-line arguments will override any set defaults.
