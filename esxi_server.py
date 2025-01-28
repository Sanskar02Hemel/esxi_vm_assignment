import socket
import json
import subprocess
import signal
import sys
import time

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

def create_snapshot(vm_id, snapshot_name):
    start_time = time.time()
    
    command = "vim-cmd vmsvc/snapshot.create {} {} \"Snapshot created via API\" 0 0".format(vm_id, snapshot_name)
    output, error = execute_commands(command)
    
    if error:
        return {"error": error}
    
    while True:
        status_cmd = "vim-cmd vmsvc/get.snapshotinfo {}".format(vm_id)
        status_output, status_error = execute_commands(status_cmd)
        
        if status_error:
            return {"error": "Failed to check snapshot status: {}".format(status_error)}
            
        if "The virtual machine is busy" in status_output:
            progress = {
                "status": "In Progress",
                "progress_percentage": 50,
                "vm_id": vm_id
            }
            time.sleep(5)  
            continue
            
        snapshot_cmd = "vim-cmd vmsvc/snapshot.get {}".format(vm_id)
        output, error = execute_commands(snapshot_cmd)
        
        if error:
            return {"error": "Failed to get snapshot details: {}".format(error)}
            
        snapshot_id = None
        lines = output.splitlines()
        for line in lines:
            if "Snapshot Id" in line:
                snapshot_id = line.split(':')[1].strip()
        
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        
        return {
            "status": "Snapshot creation complete",
            "vm_id": vm_id,
            "snapshot_id": snapshot_id,
            "snapshot_name": snapshot_name,
            "time_taken_seconds": elapsed_time,
            "progress_percentage": 100
        }

def get_snapshot_progress(vm_id):
    status_cmd = "vim-cmd vmsvc/get.snapshotinfo {}".format(vm_id)
    status_output, status_error = execute_commands(status_cmd)
    
    if status_error:
        return {"error": "Failed to check snapshot status: {}".format(status_error)}
        
    if "The virtual machine is busy" in status_output:
        return {
            "status": "In Progress",
            "progress_percentage": 50,
            "vm_id": vm_id
        }
    else:
        snapshot_cmd = "vim-cmd vmsvc/snapshot.get {}".format(vm_id)
        output, error = execute_commands(snapshot_cmd)
        
        if "Snapshot Id" in output:
            return {
                "status": "Complete",
                "progress_percentage": 100,
                "vm_id": vm_id
            }
        else:
            return {
                "status": "No snapshot operation in progress",
                "progress_percentage": 0,
                "vm_id": vm_id
            }

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
    elif action == "create_snapshot":
        return create_snapshot(vm_id, snapshot_name)
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
    server.listen(2)
    print("TCP server running on {}".format(server_address))

    signal.signal(signal.SIGINT, signal_handler)  
    signal.signal(signal.SIGTERM, signal_handler) 

    try:
        while True:
            print("Waiting for a connection...")
            client_socket, client_address = server.accept()
            print("Connection established with {}".format(client_address))

            data = client_socket.recv(1024)
            if not data:
                print("No data received, closing connection")
                client_socket.close()
                continue

            print("Raw data received: {}".format(data))
            try:
                command = json.loads(data.decode('utf-8'))
                print("Decoded command: {}".format(command))
            except json.JSONDecodeError as e:
                response = {"error": "Invalid JSON: {}".format(str(e))}
                client_socket.send(json.dumps(response).encode())
                print("Sent error response: {}".format(response))
                client_socket.close()
                continue

            response = handle_vm_operations(command)

            if response.get("status") == "Server shutting down":
                client_socket.send(json.dumps(response).encode())
                client_socket.close()
                break

            client_socket.send(json.dumps(response).encode())
            client_socket.close()

    except KeyboardInterrupt:
        print("Shutting down server...")
    finally:
        print("Closing server socket....")
        server.close()


if __name__ == "__main__":
    server_address = ("23.105.190.24", 40400)
    tcp_server(server_address)
