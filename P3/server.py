import socket
import threading
import queue
import time

# --- Configuración del Servidor ---
HOST = "127.0.0.1"
PORT = 12000
BUFFER_SIZE = 1024

# --- Estructuras de Datos Globales (Estado del Servidor) ---
# Usamos un Lock para proteger el acceso concurrente
data_lock = threading.Lock()

# 'salas' rastrea qué usuarios (por su dirección) están en qué sala
# salas = { 'general': { ('127.0.0.1', 12345), ('127.0.0.1', 54321) } }
salas = {}

# 'clientes' rastrea el nombre de usuario y la última vez que se vio
# clientes = { ('127.0.0.1', 12345): {'username': 'ana', 'last_seen': 1678886400.0} }
clientes = {}

# 'usuarios' es el inverso de 'clientes' para búsquedas rápidas de PM
# usuarios = { 'ana': ('127.0.0.1', 12345) }
usuarios = {}


def broadcast_user_list(sock, room_name):
    """
    (Req 1 & 4) Envía la lista actualizada de usuarios a todos en la sala.
    NOTA: Esta función debe ser llamada DESPUÉS de adquirir el data_lock.
    """
    print(f"[Broadcast] Actualizando lista de usuarios para '{room_name}'...")
    if room_name in salas:
        user_list = []
        for addr in salas[room_name]:
            if addr in clientes:
                user_list.append(clientes[addr]['username'])
        
        payload = ",".join(user_list)
        packet = f"USERLIST||{room_name}|{payload}".encode()
        
        for addr in salas[room_name]:
            sock.sendto(packet, addr)

def broadcast_notice(sock, room_name, message, exclude_addr=None):
    """
    Envía un mensaje de notificación (ej. "usuario se unió") a una sala.
    NOTA: Esta función debe ser llamada DESPUÉS de adquirir el data_lock.
    """
    print(f"[Notice] Enviando a '{room_name}': {message}")
    packet = f"NOTICE||{room_name}|{message}".encode()
    if room_name in salas:
        for addr in salas[room_name]:
            if addr != exclude_addr:
                sock.sendto(packet, addr)

def procesar_paquete(sock, data, addr):
    """
    Analiza el paquete de un cliente y actúa en consecuencia.
    """
    try:
        # Protocolo: COMANDO|REMITENTE|SALA_O_DESTINO|PAYLOAD
        mensaje = data.decode()
        partes = mensaje.split('|', 3)
        comando = partes[0]
        remitente = partes[1]
        sala_dst = partes[2]
        payload = partes[3]

        # Actualizar el "último visto" del cliente
        with data_lock:
            if addr in clientes:
                clientes[addr]['last_seen'] = time.time()

        # --- Lógica de Comandos ---

        if comando == "JOIN":
            with data_lock:
                username = remitente
                clientes[addr] = {'username': username, 'last_seen': time.time()}
                usuarios[username] = addr
                
                if sala_dst not in salas:
                    salas[sala_dst] = set()
                salas[sala_dst].add(addr)
                
                print(f"[JOIN] Usuario '{username}' ({addr}) se unió a '{sala_dst}'")

                broadcast_notice(sock, sala_dst, f"'{username}' se ha unido a la sala.", exclude_addr=addr)
                broadcast_user_list(sock, sala_dst)

        elif comando == "LEAVE":
            with data_lock:
                if sala_dst in salas and addr in salas[sala_dst]:
                    salas[sala_dst].remove(addr)
                    username = clientes[addr]['username']
                    print(f"[LEAVE] Usuario '{username}' ({addr}) salió de '{sala_dst}'")

                    if not salas[sala_dst]:
                        del salas[sala_dst]
                        print(f"[Server] Sala '{sala_dst}' eliminada por estar vacía.")
                    else:
                        broadcast_notice(sock, sala_dst, f"'{username}' ha salido de la sala.")
                        broadcast_user_list(sock, sala_dst)
        
        elif comando == "MSG":
            # (Req 3 - Mensajes/Emojis/Stickers)
            with data_lock:
                if sala_dst in salas and addr in salas[sala_dst]:
                    print(f"[MSG] '{remitente}' a '{sala_dst}': {payload}")
                    packet = f"MSG_BCAST|{remitente}|{sala_dst}|{payload}".encode()
                    for client_addr in salas[sala_dst]:
                        if client_addr != addr:
                            sock.sendto(packet, client_addr)

        elif comando == "PM":
            # (Req 5 - Mensajes Privados)
            # Esto AHORA retransmite CUALQUIER PM, incluidas las negociaciones de audio
            with data_lock:
                dest_username = sala_dst
                if dest_username in usuarios:
                    dest_addr = usuarios[dest_username]
                    print(f"[PM] de '{remitente}' a '{dest_username}': {payload[:30]}...")
                    # Reenviar el PM completo al destinatario
                    packet = f"PM_RECV|{remitente}||{payload}".encode()
                    sock.sendto(packet, dest_addr)
                else:
                    packet = f"NOTICE|||Usuario '{dest_username}' no encontrado.".encode()
                    sock.sendto(packet, addr)

        elif comando == "HEARTBEAT":
            # El timestamp ya se actualizó al inicio de la función.
            pass
            
    except Exception as e:
        print(f"[ERROR] Procesando paquete de {addr}: {e}\n    Paquete: {data}")


def worker_thread(sock, task_queue):
    """
    Un hilo de trabajo que saca tareas (paquetes) de la cola y los procesa.
    """
    while True:
        try:
            data, addr = task_queue.get()
            procesar_paquete(sock, data, addr)
        except Exception as e:
            print(f"[ERROR] Hilo trabajador: {e}")

def cleanup_thread(sock):
    """
    Hilo que corre periódicamente para limpiar clientes inactivos.
    """
    TIMEOUT_SEGUNDOS = 60
    
    while True:
        time.sleep(15)
        now = time.time()
        clientes_inactivos = []
        
        with data_lock:
            # 1. Encontrar inactivos
            for addr, info in clientes.items():
                if now - info['last_seen'] > TIMEOUT_SEGUNDOS:
                    clientes_inactivos.append((addr, info['username']))
            
            # 2. Eliminar inactivos
            for addr, username in clientes_inactivos:
                print(f"[Cleanup] Desconectando a '{username}' ({addr}) por inactividad.")
                
                del clientes[addr]
                if username in usuarios:
                    del usuarios[username]
                
                salas_afectadas = []
                for room_name, user_set in salas.items():
                    if addr in user_set:
                        user_set.remove(addr)
                        salas_afectadas.append(room_name)
                
                # 3. Notificar y actualizar listas (Req 4)
                for room_name in salas_afectadas:
                    if not salas[room_name]:
                        print(f"[Cleanup] Sala '{room_name}' eliminada.")
                        del salas[room_name]
                    else:
                        broadcast_notice(sock, room_name, f"'{username}' se desconectó (timeout).")
                        broadcast_user_list(sock, room_name)

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"Servidor de Chat iniciado en {HOST}:{PORT}")

    task_queue = queue.Queue()

    # Iniciar pool de hilos trabajadores
    for i in range(4):
        threading.Thread(
            target=worker_thread,
            args=(sock, task_queue),
            daemon=True
        ).start()
    
    # Iniciar hilo de limpieza
    threading.Thread(
        target=cleanup_thread,
        args=(sock,),
        daemon=True
    ).start()

    # El hilo principal se convierte en el Hilo Receptor
    print("Servidor listo. Esperando paquetes...")
    while True:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            task_queue.put((data, addr))
        except Exception as e:
            print(f"Error en Hilo Receptor: {e}")

if __name__ == "__main__":
    main()