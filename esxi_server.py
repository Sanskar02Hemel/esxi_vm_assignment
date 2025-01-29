import socket
import json
import subprocess
import signal
import sys
import time
import re
import threading
from datetime import datetime
class ClientHandler(threading.Thread):
    def __init__(self, client_socket, client_address):
        threading.Thread.__init__(self)
        self.client_socket = client_socket
        self.client_address = client_address

    def run(self):
        try:
            data = self.client_socket.recv(1024)
            if not data:
                print("No data received, closing connection")
                self.client_socket.close()
                return

            print("Raw data received: {}".format(data))
            try:
                command = json.loads(data.decode('utf-8'))
                print("Decoded command: {}".format(command))
                response = handle_vm_operations(command)
                self.client_socket.send(json.dumps(response).encode())
                print("Sent response: {}".format(response))
            except json.JSONDecodeError as e:
                response = {"error": "Invalid JSON: {0}".format(str(e))}
                self.client_socket.send(json.dumps(response).encode())
                print("Sent error response: {}".format(response))
        finally:
            self.client_socket.close()

def execute_commands(command):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True, 
            executable="/bin/sh"  
        )
        if result.returncode == 0:
            return result.stdout.strip(), None
        else:
            return None, result.stderr.strip()
    except Exception as e:
        return None, str(e)

def get_all_vms():
    command = "vim-cmd vmsvc/getallvms"
    output, error = execute_commands(command)

    if error: 
        return {"error": error}
    
    vms = []
    lines = output.splitlines()[1:]
    for line in lines:
        parts = line.split()
        vm_id = parts[0]
        name = parts[1]
        path = parts[-1]
        vms.append({"vm_id": vm_id, "name": name, "path": path})
    return {"vms": vms}

def manage_vm_power(vm_id, action):
    command_map = {
        "power_on": "vim-cmd vmsvc/power.on {}".format(vm_id),
        "power_off": "vim-cmd vmsvc/power.off {}".format(vm_id),
        "reboot": "vim-cmd vmsvc/power.reboot {}".format(vm_id)
    }

    command = command_map.get(action)
    if not command:
        return {"error": "Invalid action specified"}

    output, error = execute_commands(command)
    if error: 
        return {"error": error}
    return {"status": "Vm {} successfully.".format(action)}

def get_latest_snapshot_task(vm_id):
    command = "vim-cmd vmsvc/get.tasklist {}".format(vm_id)
    output, error = execute_commands(command)
    
    if error:
        return None

    tasks = output.splitlines()
    create_snapshot_tasks = [
        task.strip("',") for task in tasks 
        if 'createSnapshot' in task
    ]

    if not create_snapshot_tasks:
        return None

    latest_task = create_snapshot_tasks[0]
    task_match = re.search(r"haTask-\d+-vim\.VirtualMachine\.createSnapshot-\d+", latest_task)
    return task_match.group(0) if task_match else None

def get_task_info(task_id):
    command = "vim-cmd vimsvc/task_info '{0}'".format(task_id)
    output, error = execute_commands(command)
    
    if error:
        return None

    task_info = {
        'state': 'unknown',
        'progress': 0,
        'start_time': None,
        'complete_time': None
    }

    if output:
        for line in output.splitlines():
            if 'state = "' in line:
                task_info['state'] = line.split('"')[1]
            elif 'progress = ' in line:
                progress_str = line.split('=')[1].strip(' ,')
                task_info['progress'] = int(progress_str) if progress_str.isdigit() else 0
            elif 'startTime = "' in line:
                task_info['start_time'] = line.split('"')[1]
            elif 'completeTime = "' in line:
                task_info['complete_time'] = line.split('"')[1]

    return task_info

def create_snapshot(vm_id, snapshot_name, description="Snapshot created via API"):
    command = 'vim-cmd vmsvc/snapshot.create {0} "{1}" "{2}" 1 0'.format(
        vm_id, snapshot_name, description
    )
    output, error = execute_commands(command)

    if error:
        return {"error": error}

    time.sleep(1)

    start_time = time.time()
    while True:
        task_id = get_latest_snapshot_task(vm_id)
        if not task_id:
            time.sleep(1)
            continue

        task_info = get_task_info(task_id)
        if not task_info:
            time.sleep(1)
            continue

        if task_info['state'] == 'success':
            end_time = time.time()
            elapsed_time = end_time - start_time

            if task_info['start_time'] and task_info['complete_time']:
                try:
                    start = datetime.strptime(task_info['start_time'], "%Y-%m-%dT%H:%M:%S.%fZ")
                    complete = datetime.strptime(task_info['complete_time'], "%Y-%m-%dT%H:%M:%S.%fZ")
                    elapsed_time = (complete - start).total_seconds()
                except ValueError:
                    pass  

            return {
                "status": "Snapshot creation complete",
                "vm_id": vm_id,
                "snapshot_name": snapshot_name,
                "time_taken_seconds": elapsed_time
            }
        elif task_info['state'] == 'error':
            return {
                "status": "Error creating snapshot",
                "vm_id": vm_id,
                "error": "Task failed"
            }

        time.sleep(1)

def get_snapshot_progress(vm_id):
    task_id = get_latest_snapshot_task(vm_id)
    if not task_id:
        return {
            "status": "No snapshot operation in progress",
            "progress_percentage": 0,
            "vm_id": vm_id
        }

    task_info = get_task_info(task_id)
    if not task_info:
        return {
            "error": "Failed to get task information",
            "vm_id": vm_id
        }

    response = {
        "vm_id": vm_id,
        "progress_percentage": task_info['progress'],
        "state": task_info['state']
    }

    if task_info['state'] == 'success':
        elapsed_time = None
        if task_info['start_time'] and task_info['complete_time']:
            try:
                start = datetime.strptime(task_info['start_time'], "%Y-%m-%dT%H:%M:%S.%fZ")
                complete = datetime.strptime(task_info['complete_time'], "%Y-%m-%dT%H:%M:%S.%fZ")
                elapsed_time = (complete - start).total_seconds()
            except ValueError:
                elapsed_time = None

        response.update({
            "status": "Complete",
            "time_taken_seconds": elapsed_time
        })
    elif task_info['state'] == 'running':
        response.update({
            "status": "In Progress"
        })
    else:
        response.update({
            "status": task_info['state']
        })

    return response

def get_vm_count():
    result = get_all_vms()
    if "error" in result:
        return result  

    total_vms = len(result["vms"])
    return {"total_vms": total_vms}

def revert_snapshot(vm_id, snapshot_id=None):
    command = "vim-cmd vmsvc/snapshot.get {}".format(vm_id)
    output, error = execute_commands(command)

    if error:
        return {"error": "Failed to get snapshot details: {}".format(error)}

    snapshot_hierarchy = []
    lines = output.splitlines()
    for line in lines:
        if "Snapshot Id" in line:
            snap_id = line.split(":")[1].strip()
            snapshot_hierarchy.append(snap_id)

    if not snapshot_hierarchy:
        return {"error": "No snapshots found for this VM."}

    target_snapshot_id = snapshot_id if snapshot_id else snapshot_hierarchy[-1]

    command = "vim-cmd vmsvc/snapshot.revert {} {} 0".format(vm_id, target_snapshot_id)
    output, error = execute_commands(command)

    if error:
        return {"error": error}

    return {"status": "Reverted to snapshot {} successfully.".format(target_snapshot_id)}

def remove_snapshots(vm_id):
    command = "vim-cmd vmsvc/snapshot.removeall {}".format(vm_id)

    output, error = execute_commands(command)
    if error:
        return {"error": error}
    return {"status": "All Snapshots for VM: {} removed successfully".format(vm_id)}

def handle_vm_operations(command):
    action = command.get("action")
    vm_id = command.get("vm_id")
    snapshot_name = command.get("snapshot_name", "Snapshot")
    snapshot_id = command.get("snapshot_id")
    description = command.get("description", "Snapshot created via API")

    if action == "list_vms":
        return get_all_vms()
    elif action == "get_vm_count":
        return get_vm_count()
    elif action == "power_on":
        return manage_vm_power(vm_id, "power_on")
    elif action == "power_off":
        return manage_vm_power(vm_id, "power_off")
    elif action == "reboot":
        return manage_vm_power(vm_id, "reboot")
    if action == "create_snapshot":
        return create_snapshot(vm_id, snapshot_name, description)
    elif action == "get_snapshot_progress":
        return get_snapshot_progress(vm_id)
    elif action == "revert_snapshot":
        return revert_snapshot(vm_id, snapshot_id)
    elif action == "remove_snapshots":
        return remove_snapshots(vm_id)
    elif action == "shutdown":
        return {"status": "Server shutting down"}
    else:
        return {"error": "Invalid action"}

def signal_handler(signum, frame):
    print("\nShutting down server gracefully...")
    sys.exit(0)

def tcp_server(server_address):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(server_address)
    server.listen(5) 
    print("TCP server running on {}".format(server_address))

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while True:
            print("Waiting for a connection...")
            client_socket, client_address = server.accept()
            print("Connection established with {}".format(client_address))

            client_handler = ClientHandler(client_socket, client_address)
            client_handler.daemon = True
            client_handler.start()

    except KeyboardInterrupt:
        print("Shutting down server...")
    finally:
        print("Closing server socket....")
        server.close()


if __name__ == "__main__":
    server_address = ("23.105.190.24", 40400)
    tcp_server(server_address)
