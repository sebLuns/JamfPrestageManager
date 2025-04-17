import requests
import argparse
import json
import re
import getpass
from requests.auth import HTTPBasicAuth



# command-line argument support implementation
parser = argparse.ArgumentParser(description="Command-line driven utility for Jamf prestages that provides better multi-prestage support and error handling.", add_help=False)
parser.add_argument("--help", action="store_true", help="Show this help message and exit.")
parser.add_argument("--url", help="Your Jamf Instance URL, ex. \"https://yourinstance.jamfcloud.com\"")
parser.add_argument("--username", help="Your Jamf login username")
parser.add_argument("--targetid", metavar= "ID", help="The ID of the prestage you want devices in your CSV to move to. Use \"0\" to use the Default prestage in Jamf, or \"-1\" to unassign devices.")
parser.add_argument("--targetname", metavar= "NAME", help="The name of the prestage you want devices in your CSV to move to. Overrides --targetid.")
parser.add_argument("--file", help="CSV file of device serials (without header) that you wish to process.")
parser.add_argument("--computer", action="store_true", help="Use Computer Prestages")
parser.add_argument("--mobile", action="store_true", help="Use Mobile Device Prestages")
parser.add_argument("--append", action="store_true", help="Append all devices in CSV to a prestage")
parser.add_argument("--exact", action="store_true", help="Move any devices not in CSV out of the target prestage.")
parser.add_argument("--defaultid", metavar= "ID", help="Exact mode only: The ID of the prestage you want all extra devices to be moved to. Use \"0\" to use the Default prestage in Jamf, or \"-1\" to leave devices unassigned.")
parser.add_argument("--defaultname", metavar= "NAME", help="Exact mode only: The name of the prestage you want all extra devices to be moved to. Overrides --defaultid.")
parser.add_argument("--bulk", action="store_true", help="Move devices in bulk groups.")
parser.add_argument("--granular", action="store_true", help="Move devices one at a time (NOT RECOMMENDED).")
args = parser.parse_args()

if args.help:
    print("")
    parser.print_help()
    print("")
    exit()

#######################################################################
###### BEGIN MAIN VARIABLE DECLARATIONS
#######################################################################

# Global declarations
global token
global bad_device_report
global jss_url
global jss_username
global jss_password

# Constants by virtue
mobile_device_scopes_url = "/api/v2/mobile-device-prestages/"
computer_scopes_url = "/api/v2/computer-prestages/"
remove_scope_suffix = "/scope/delete-multiple/"
add_scope_suffix = "/scope/"

# API Token
token = None

# Array that will contain all errors thrown by bad device serials
bad_device_report = []


#######################################################################
###### BEGIN USER-DEFINED DEFAULTS
#######################################################################

# Variables can be defined here to skip configuring 
# via command-line arguments or guided definitions
# Specifying command-line arguments will override these settings.

# Your Jamf Instance URL, ex. "https://yourinstance.jamfcloud.com"
jss_url = ""

# Your Jamf login username
jss_username = ""

# Device Class (Comptuer/Mobile): Move devices using computer or 
# mobile device prestages.
device_class = ""

# Exact mode only -- The ID of the prestage you want all extra devices
# to be moved to.
default_prestage_id = ""

# Operation mode (Append/Exact): Append devices to prestage (Append) or
# Make the devices in your CSV the only devices in prestage (Exact)
op_mode = ""

# Speed mode (Bulk/Granular): Attempt to move as many devices in 
# bulk groups (Bulk) or move them one at a time (Granular). 
# Granular mode is not recommended except for emergencies.
speed_mode = ""

#######################################################################


#######################################################################
###### BEGIN UTILITY FUNCTION DEFINITIONS
#######################################################################


# API Token Generator. User credentials must have sufficient permission 
# to move devices between prestages. On failure, will attempt to get a 
# token 2 more times. 
def generate_token(attempts=0):
    
    global token
    global jss_url
    global jss_username
    global jss_password
    
    print("\nGenerating new API token")
    token_headers = { "Accept" : "application/json"}
    token_request = requests.post(jss_url+"/api/v1/auth/token", headers=token_headers, auth=HTTPBasicAuth(jss_username, jss_password))

    if token_request.status_code != 200:
        if attempts > 2:
            print(f"There appears to be some kind of authorization error. JSS responded:\n{token_request.text}\n\nPlease try again later.\n")
            exit()
        else:
            print("Couldn't generate new token. Trying again...")
            generate_token(attempts=attempts+1)
    else:
        token = token_request.json()['token']

# Invalidates current token.
def kill_token():
    global token
    global jss_url
    kill_headers = { "Accept" : "application/json", "Authorization" : "Bearer " + token }
    kill_request = requests.post(jss_url+"/api/v1/auth/invalidate-token", headers=kill_headers)
    if kill_request.status_code != 204:
        print(f"There appears to be some kind of authorization error. JSS responded:\n{kill_request.text}")

# Handles regenerating bad tokens, and removing/logging bad serials from the provided CSV
def error_handler(bad_request, serials=[]):

    global bad_device_report

    if bad_request.json()['errors'][0]['code'] == "INVALID_TOKEN":
        generate_token()
        return None

    if bad_request.json()['httpStatus'] == 400:
        if len(serials) > 1:
            print("Attempting to remove bad devices from list. Retrying command...")
            for error in bad_request.json()['errors']:
                if error['field'] == "serialNumbers":
                    serials.remove(error['description'])
                    bad_device_report.append(error)
            return serials
        else:
            print("Skipping bad device...")
            bad_device_report.append(bad_request.json()['errors'][0])
            return []
            
# Jamf requires an "Optimistic Lock" to move devices between prestages 
# to prevent race conditions. Uses error_handler for token checking.
def get_lock_number(url, attempts=0):
    
    headers = {"Accept" : "application/json", "Content-Type": "application/json", "Authorization" : "Bearer " + token }

    lock_request = requests.get(url + "/scope", headers=headers)
    if lock_request.status_code != 200:
        print(f"JSS responded with the following error:\n{lock_request.text}")
        if attempts > 2:
            print("Failed to get Optimistic Lock code. Please try again later.")
            exit()
        else:
            print("Error getting Optimistic Lock code. Trying again...")
            error_handler(lock_request)
            lock_request = get_lock_number(url, attempts=attempts+1)

    return lock_request.json()['versionLock']
    
    
# API commands that facilitate moving devices between prestages. 
# Attempts to get Optimistic Lock, then uses it to move devices. 
# Uses error_handler to remove bad devices from the array and retry.
def move_devices(url, url_suffix, devices, attempts=0):

    headers = {"Accept" : "application/json", "Content-Type": "application/json", "Authorization" : "Bearer " + token }

    move_payload = { "serialNumbers" : devices, "versionLock" : get_lock_number(url) }

    move_request = requests.post(url + url_suffix, json=move_payload, headers=headers)
    
    if move_request.status_code != 200:
        
        if attempts > 2:
            print("Failed to perform command. Skipping...")
            return None

        else:
            print(f"JSS responded with the following error:\n{move_request.text}")
            devices = error_handler(move_request, devices)
            move_request = move_devices(url, url_suffix, devices, attempts=attempts+1)
                
    else:
        print("Success!")


# All errors caused by bad device serials are appended to an array.
# If this array contains any elements, the users is asked if they want 
# to view them at the end of a run. Common errors are displayed in a 
# simple view prior to the raw error messages being printed.
def print_bad_device_report():

    global jss_url

    print("\n\nGenerating report...\n")

    headers = {"Accept" : "application/json", "Content-Type": "application/json", "Authorization" : "Bearer " + token }

    test_auth = requests.get(jss_url+"/api/v1/auth/", headers=headers)
    if test_auth.status_code != 200:
        generate_token()
        headers['Authorization'] = "Bearer " + token

    for error in bad_device_report:

        error_info = ""

        serial = error['description']
        error_info += f"Device Serial: {serial}"

        info_request = requests.get(jss_url+"/JSSResource/mobiledevices/serialnumber/" + serial, headers=headers)
        if info_request.status_code == 200:
            if 'asset_tag' in info_request.json()['mobile_device']['general'] and info_request.json()['mobile_device']['general']['asset_tag'] != "" and info_request.json()['mobile_device']['general']['asset_tag'] != serial:
                error_info += f"Asset Tag: {info_request.json()['mobile_device']['general']['asset_tag']}"
            else:
                error_info += "\nThis device is in Jamf but does not have an asset tag."
        else:
            error_info += "\nThis device is not in Jamf.\nIt may be mistyped or might not have ever been enrolled before."

        error_info += f"\nRaw Error Info:\n{json.dumps(error, sort_keys=True, indent=2, separators=(',', ': '))}"

        print(error_info + "\n")

    print("\nReport complete.")


#######################################################################
###### BEGIN MAIN FUNCTION DEFINITION
#######################################################################

# Main program is wrapped in its own function to facilitate killing the API token 
# if CTRL+C is pressed at any time in the program.
try:

    # Set Jamf Instance URL 
    if args.url is not None:
        jss_url = args.url
    elif jss_url == "":
        jss_url = input("\nEnter the url of your JSS instance: ")
    jss_url = jss_url.rstrip("/ ")

    # Get user credentials
    if args.username is not None:
        jss_username = args.username

    if jss_username == "":
        jss_username = input("\nEnter your JSS Username: ")
    else:
        print(f"\nUsing supplied username: {jss_username}")

    jss_password = getpass.getpass("Enter your JSS Password: ")

    # Get Token
    generate_token()

    # Set device class
    if args.computer:
        scopes_url = jss_url + computer_scopes_url
    elif args.mobile:
        scopes_url = jss_url + mobile_device_scopes_url
    elif device_class.lower() == "computer":
        scopes_url = jss_url + computer_scopes_url
    elif device_class.lower() == "mobile":
        scopes_url = jss_url + mobile_device_scopes_url
    else:
        device_class = input("\nEnter the device class you want to move (Computer/Mobile): ")
        if device_class.lower() == "computer":
            scopes_url = jss_url + computer_scopes_url
        elif device_class.lower() == "mobile":
            scopes_url = jss_url + mobile_device_scopes_url
        else:
            print("\nInvalid device class\n")
            exit()

    # Set Operation Mode
    if args.append or args.exact:
        if args.append:
            option = "append"
        else:
            option = "exact"
    elif op_mode.lower() == "exact" or op_mode.lower() == "append":
        option = op_mode
    else:
        print("\n\"Exact\" mode will assign all devices in a CSV to a given Prestage ID, \nand moves any devices from that Prestage that aren't in that CSV to \nthe DEP Prestage.")
        print("\n\"Append\" mode simply moves any devices from any CSV to a given Prestage \nand leaves all other devices where they are.")
        option = input("\nChoose a mode (Exact/Append): ")

        if not option.lower() == "exact" and not option.lower() == "append":
            print("\nInvalid operation mode\n")
            exit()

    # Set Speed Mode
    if args.bulk or args.granular:
        if args.bulk:
            speed = "bulk"
        else:
            speed = "granular"
    elif op_mode.lower() == "bulk" or op_mode.lower() == "granular":
        option = op_mode
    else:
        print("\nThe \"Bulk\" setting will attempt to move devices en masse by their \nPrestage ID, which is faster.")
        print("\nThe \"Granular\" setting will move devices one by one by their serial \nnumber, which is slower-- but if one device causes an error then it \nwill not affect any other devices.")
        speed = input("\nChoose a setting (Bulk/Granular): ")

        if not speed.lower() == "bulk" and not speed.lower() == "granular":
            print("\nInvalid speed setting\n")
            exit()


    # Get device scoping info
    print("\nGetting scope info for all devices")
    scopes_headers = { "Accept" : "application/json", "Authorization" : "Bearer " + token }
    scopes_request = requests.get(scopes_url + "scope", headers=scopes_headers)
    scoped_serials = scopes_request.json()["serialsByPrestageId"]


    # Get info of all scope names and IDs. Hard limit of 200 prestages.
    scope_info_request = requests.get(scopes_url + "?page-size=200&sort=displayName%3Aasc", headers=scopes_headers)

    jamf_set_default_id = ""

    # Dictionary that will contain all prestage names, with their jamf IDs as keys
    scope_names = {}

    for prestage in scope_info_request.json()['results']:
        scope_names[prestage['id']] = prestage['displayName']
        if prestage['defaultPrestage'] == True:
            jamf_set_default_id = prestage['id']


    # Determine theoretical prestage max ID in order to determine bulk movements
    print(f'\nTotal number of scoped devices: {len(scoped_serials)}')
    max_prestages = 0
    for scope in scope_names:
        if int(scope) > max_prestages:
            max_prestages = int(scope)


    # Set target prestage ID
    target_id =""
    if args.targetid is not None and (args.targetid in scope_names or args.targetid == "-1"):
        target_id = args.targetid
    elif args.targetid is not None and jamf_set_default_id != "" and args.targetid == "0":
        target_id = jamf_set_default_id

    if args.targetname is not None:
        for prestage in scope_names:
            if args.targetname.lower() == scope_names[prestage].lower():
                target_id = prestage

    while target_id == "" or target_id.lower() == "list":
        print("\nEnter the ID or name of the prestage you wish to target.")
        print("Type \"-1\" to leave extra devices unassigned from any prestage.")
        if jamf_set_default_id != "":
            print(f"Leave blank to use default Prestage set in Jamf ({scope_names[jamf_set_default_id]}). ")
        target_id = input("Alternatively, type \"list\" to see a list of all prestages and their IDs: ")
        if target_id == "list":
            print()
            for prestage in scope_names:
                print(f"{scope_names[prestage]}: {prestage}")
        elif target_id.isnumeric() or target_id == "-1":
            if target_id not in scope_names and target_id != "-1":
                print("\nThis does not appear to be a valid prestage ID number.")
                target_id = ""
        elif target_id == "" and jamf_set_default_id != "":
            target_id = jamf_set_default_id
        else:
            for prestage in scope_names:
                if target_id.lower() == scope_names[prestage].lower():
                    target_id = prestage
            if not target_id in scope_names:
                print("\nThis does not appear to be a valid prestage name.")
                target_id = ""


    # Set default prestage ID
    if args.defaultid is not None and (args.defaultid in scope_names or args.defaultid == "-1"):
        default_prestage_id  = args.defaultid
    elif args.defaultid is not None and jamf_set_default_id != "" and args.defaultid == "0":
        default_prestage_id = jamf_set_default_id
    elif default_prestage_id != "" and default_prestage_id not in scope_names:
        default_prestage_id = ""

    if args.defaultname is not None:
        for prestage in scope_names:
            if args.defaultname.lower() == scope_names[prestage].lower():
                default_prestage_id = prestage

    while option.lower() == "exact" and default_prestage_id == "":
        print("\nExact mode enabled. Please enter the ID of the prestage you want extra devices to be moved to. ")
        print("Type \"-1\" to leave extra devices unassigned from any prestage.")
        if jamf_set_default_id != "":
            print(f"Leave blank to use default Prestage set in Jamf ({scope_names[jamf_set_default_id]}). ")
        default_prestage_id = input("Alternatively, type \"list\" to see a list of all prestages and their IDs: ")
        if default_prestage_id == "list":
            print()
            for prestage in scope_names:
                print(f"{scope_names[prestage]}: {prestage}")
        elif default_prestage_id.isnumeric() or default_prestage_id == "-1":
            if default_prestage_id not in scope_names and default_prestage_id != "-1":
                print("\nThis does not appear to be a valid prestage ID number.")
                default_prestage_id = ""
        elif default_prestage_id == "" and jamf_set_default_id != "":
            default_prestage_id = jamf_set_default_id
        else:
            for prestage in scope_names:
                if default_prestage_id.lower() == scope_names[prestage].lower():
                    default_prestage_id = prestage
            if not default_prestage_id in scope_names:
                print("\nThis does not appear to be a valid prestage name.")
                default_prestage_id = ""


    # Sanity check -- Target and Default prestages cannot match in exact mode.
    if option.lower() == "exact" and target_id == default_prestage_id:
        print("\nERROR: Target Prestage ID and Default Prestage ID must not be the same during Exact mode.\n\nKilling API token and exiting...\n")
        kill_token()
        exit()


    # Determine number of devices in target prestage
    scoped_count = 0
    for serial in scoped_serials:
        if (target_id != "-1"  and scoped_serials[serial] == target_id):
            scoped_count += 1

    if target_id != "-1":
        print(f'\nTotal number of devices in target prestage {scope_names[target_id]}: {scoped_count}\n')


    # Set up a series of empty arrays to later map out bulk transfer movements
    if speed.lower() == "bulk":
        bulk_transfers = {}
        for i in range(max_prestages + 1):
            bulk_transfers[i] = []

    # Load file by path
    file = None
    if args.file is not None:
        target_file = args.file
    else:
        target_file = input("\nEnter the path of the CSV of serials you wish to process or drag the file into the terminal. \nThe file must not have a header: ")    
        print("\n")

    while file is None:
        try:
            file = open(target_file.strip(), "r", encoding="utf-8")
            file_serials = file.readlines()
        except:
            print("ERROR: The file name/path entered either does not exist or contains non-CSV data.")
            target_file = input("\nEnter the path of the CSV of serials you wish to process or drag the file into the terminal. \nThe file must not have a header: ")
            print("\n")

    
    target_serials = []

    # Scrub any junk data out of serial numbers (useful for laser scanning errors) and add to an array
    for serial in file_serials:
        target_serials.append(re.sub(r'\W+', '', serial.strip().upper()))


    # Count number of devices already in target prestage and report to user
    existing_count = 0
    for serial in target_serials:
        if serial in scoped_serials:
            if (target_id != "-1"  and scoped_serials[serial] == target_id):
                existing_count += 1

    if existing_count > 0 and target_id != "-1":
        print(f"Found {existing_count} of {len(target_serials)} devices already in {scope_names[target_id]}\n")

    if target_id != "-1":
        print(f"Preparing to move {len(target_serials) - existing_count} devices to {scope_names[target_id]}...")
    else:
        print(f"\nPreparing to unassign up to {len(target_serials)} devices...")

    # Move devices one at a time
    if speed.lower() == "granular":
        
        for serial in target_serials:

            if not serial in scoped_serials:
                
                if target_id != "-1":
                    print(f"\nAttempting to add the unassigned device {serial} to {scope_names[target_id]}")
                    move_devices(url=scopes_url + target_id, url_suffix=add_scope_suffix, devices=[serial])
                else:
                    print(f"\nDevice {serial} already unassigned.")

            elif scoped_serials[serial] != target_id:
                
                print(f"\nAttempting to remove device {serial} from {scope_names[scoped_serials[serial]]}")    
                move_devices(url=scopes_url + scoped_serials[serial], url_suffix=remove_scope_suffix, devices=[serial])
                if target_id != "-1":
                    print(f"\nAttempting to move device {serial} to prestage {scope_names[target_id]}") 
                    move_devices(url=scopes_url + target_id, url_suffix=add_scope_suffix, devices=[serial])

        # Move any extra devices to default prestage
        if option.lower() == "exact":

            for serial in scoped_serials:
                if scoped_serials[serial] == target_id and not serial in target_serials:
                    print(f"\nAttempting to remove device {serial} from {scope_names[target_id]}")    
                    move_devices(url=scopes_url + target_id, url_suffix=remove_scope_suffix, devices=[serial])
                    if default_prestage_id != "-1":
                        print(f"\nAttempting to move device {serial} to {scope_names[default_prestage_id]}") 
                        move_devices(url=scopes_url + default_prestage_id, url_suffix=add_scope_suffix, devices=[serial])

    if speed.lower() == "bulk":

        for serial in target_serials:

            if not serial in scoped_serials:
                bulk_transfers[0].append(serial)
            else:
                if scoped_serials[serial] != target_id:
                    bulk_transfers[int(scoped_serials[serial])].append(serial)

        for prestage_id in bulk_transfers:
            if len(bulk_transfers[prestage_id]) > 0 and not (prestage_id == 0 and target_id == "-1"):
                if prestage_id == 0:
                    print(f"\nAttempting to move {len(bulk_transfers[prestage_id])} unassigned devices to {scope_names[target_id]}")
                    move_devices(url=scopes_url + target_id, url_suffix=add_scope_suffix, devices=bulk_transfers[prestage_id])
                    
                else:
                    print(f"\nAttempting to remove {len(bulk_transfers[prestage_id])} devices from {scope_names[str(prestage_id)]}")
                    move_devices(url=scopes_url + str(prestage_id), url_suffix=remove_scope_suffix, devices=bulk_transfers[prestage_id])
                    if target_id != "-1":
                        print(f"\nAttempting to move {len(bulk_transfers[prestage_id])} devices to {scope_names[target_id]}")
                        move_devices(url=scopes_url + target_id, url_suffix=add_scope_suffix, devices=bulk_transfers[prestage_id])
            
            elif prestage_id == 0 and target_id == "-1":
                print(f"\n{len(bulk_transfers[prestage_id])} devices already unassigned.")

        # Moves all devices in prestage not found in CSV to default prestage all at once.            
        if option.lower() == "exact":

            dep_devices = []
            for serial in scoped_serials:
                if scoped_serials[serial] == target_id and not serial in target_serials:
                    dep_devices.append(serial)

            if len(dep_devices) > 0:
                print(f"\nAttempting to remove {len(dep_devices)} devices from {scope_names[target_id]}")
                move_devices(url=scopes_url + target_id, url_suffix=remove_scope_suffix, devices=dep_devices)
                if default_prestage_id != "-1":
                    print(f"\nAttempting to move {len(dep_devices)} devices to {scope_names[default_prestage_id]}")
                    move_devices(url=scopes_url + default_prestage_id, url_suffix=add_scope_suffix, devices=dep_devices)


    # Confirm completion and inquire about printing errors.
    print("\nOperation completed!")

    if len(bad_device_report) > 0:
        print(f"\nA total of {len(bad_device_report)} errors were encountered during the operation.")
        error_choice = input("Type 'Y' to generate a report on all errors: ")
        if error_choice.lower() == 'y':
            print_bad_device_report()


    # Close out program, killing API Token.
    print("\nKilling API token and exiting...\n")
    kill_token()

except KeyboardInterrupt:
    print("\n\nKeyboard Interrupt detected. Killing API token and exiting...\n")
    if token is not None:
        kill_token()
