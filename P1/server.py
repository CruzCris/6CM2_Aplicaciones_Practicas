# Servidor -> Socket de flujo bloqueante

import socket
import select
import json
import os
import sys
import traceback
import re
import time

# Configuración de la conexión
HOST = '0.0.0.0'
PORT = 9999
BUFFER_SIZE = 4096
INVENTORY_FILE = 'inventario.json'
MAX_CONNECTIONS = 10

# Variables globales auxiliares
INVENTARIO = {}
CLIENTE_CARRITOS = {}

# Diccionario de buffers por cliente
CLIENT_BUFFERS = {}

# Lista de sockets que select monitorea para lectura
SOCKET_LIST = [] 
SERVER_SOCKET_FILENO = None

def cargar_inventario():
    # Carga los datos del inventario desde el archivo JSON
    global INVENTARIO
    
    if not os.path.exists(INVENTORY_FILE):
        print(f"ERROR: El archivo '{INVENTORY_FILE}' no existe.")
        return
    try:
        with open(INVENTORY_FILE, 'r') as f:
            INVENTARIO = json.load(f)
        print(f"Inventario cargado exitosamente.")
    except json.JSONDecodeError:
        print(f"ERROR: No se pudo decodificar el archivo JSON.")
        INVENTARIO = {}
    except Exception as e:
        print(f"No se pudo cargar el inventario: {e}")
        INVENTARIO = {}

def guardar_inventario():
    # Guarda los datos del inventario actualizado
    try:
        with open(INVENTORY_FILE, 'w') as f:
            json.dump(INVENTARIO, f, indent=4)
        print(f"Inventario guardado en '{INVENTORY_FILE}'.")
        return True
    except Exception as e:
        print(f"No se pudo guardar el inventario: {e}")
        return False

def buscar_inventario(param: str):
    # Busca productos por nombre o marca
    resultados = {}
    param = param.lower()
    for id, producto in INVENTARIO.items():
        if param in producto.get('nombre', '').lower() or param in producto.get('marca', '').lower():
            resultados[id] = producto
    return resultados

def listar_tipo(tipo: str):
    # Lista productos filtrando por el campo 'tipo'
    resultados = {}
    tipo = tipo.lower()
    for id, producto in INVENTARIO.items():
        if producto.get('tipo', '').lower() == tipo:
            resultados[id] = producto
    return resultados

def stock_producto(id: str) -> int:
    # Obtiene el stock disponible de un producto
    return INVENTARIO.get(id, {}).get('stock', 0)

def parseo(msj: str) -> tuple:
    # Parsear el mensaje del cliente para saber que accion realizar
    partes = msj.strip().split()
    accion = partes[0].upper() if partes else ""
    params = partes[1:]
    return accion, " ".join(params) 

# Funciones para manejar la comunicación con el cliente

def envio_respuesta(conn, status, data):
    # Enviar respuesta serializada al cliente
    try:
        cuerpo_respuesta = json.dumps(data)
        respuesta_final = f"{status} {cuerpo_respuesta}\n"
        
        # EL USO DE conn.sendall() ES BLOQUEANTE
        conn.sendall(respuesta_final.encode('utf-8'))
    except Exception as e:
        print(f"No se pudo enviar la respuesta: {e}")

def procesar_comando(cliente_id, message):
    # Lógica central para procesar un comando ya completo
    global INVENTARIO, CLIENTE_CARRITOS

    # Parseamos el comando
    accion, param_str = parseo(message)
    params = param_str.split()
    conn = next(sock for sock in SOCKET_LIST if sock.fileno() == cliente_id) # Obtener el socket del cliente
    
    # Inicializamos las variables de respuesta
    respuesta_data = None
    respuesta_status = "OK"
    
    # Obtenemos el carrito del cliente
    carrito_actual = CLIENTE_CARRITOS.get(cliente_id, {})
    
    if accion == "VER_PRODUCTOS":
        data_with_id = {}
        for id, product in INVENTARIO.items():
            product['id'] = id
            data_with_id[id] = product
        respuesta_data = data_with_id

    elif accion == "BUSCAR" or accion == "LISTAR":
        if not param_str:
            respuesta_status = "ERROR"
            respuesta_data = "Debe proporcionar un parametro para buscar o listar."
        else:
            respuesta_data = buscar_inventario(param_str) if accion == "BUSCAR" else listar_tipo(param_str)
    
    elif accion == "AGREGAR_CARRITO" or accion == "EDITAR_CARRITO":
        # Validación de parámetros
        if len(params) < 2:
            respuesta_status = "ERROR"
            respuesta_data = "Faltan parametros para poder realizar la accion (ID y CANTIDAD)."
        else:
            producto_id = params[0]
            try:
                # Validamos que la cantidad sea un entero
                cantidad = int(params[1])
            except ValueError:
                respuesta_status = "ERROR"; respuesta_data = "La cantidad debe ser un numero entero."
                
            if respuesta_status == "OK":
                # Validamos que el producto exista
                if producto_id not in INVENTARIO:
                    respuesta_status = "ERROR"; respuesta_data = f"No existe el producto con el ID {producto_id}."
                else:
                    nombre_producto = INVENTARIO[producto_id]['nombre']
                    
                    # Cálculo de nueva cantidad total
                    cant_actual_carrito = carrito_actual.get(producto_id, 0)
                    nueva_cant_total = cant_actual_carrito + cantidad if accion == "AGREGAR_CARRITO" else cantidad

                    # Validación de Stock y rangos
                    stock_disp = stock_producto(producto_id)
                    
                    if nueva_cant_total < 0:
                        respuesta_status = "ERROR"; respuesta_data = "La cantidad no puede ser menor a cero."
                    elif nueva_cant_total > stock_disp:
                        respuesta_status = "ERROR"; respuesta_data = f"Stock insuficiente. Disponible: {stock_disp}. Solicitado: {nueva_cant_total}."
                    
                    # Si todo es OK, actualizar carrito
                    elif respuesta_status == "OK":
                        if nueva_cant_total == 0:
                            if producto_id in carrito_actual: del CLIENTE_CARRITOS[cliente_id][producto_id]
                            respuesta_data = {"mensaje": f"Se eliminó '{nombre_producto}' del carrito."}
                        else:
                            CLIENTE_CARRITOS[cliente_id][producto_id] = nueva_cant_total
                            respuesta_data = {"mensaje": f"Carrito actualizado. '{nombre_producto}' total: {nueva_cant_total}."}
    
    elif accion == "VER_CARRITO":
        productos_carrito = CLIENTE_CARRITOS.get(cliente_id, {})
        carrito = {}
        for id, cant in productos_carrito.items():
            if id in INVENTARIO:
                carrito[id] = {
                    "nombre": INVENTARIO[id]['nombre'],
                    "precio": INVENTARIO[id]['precio'],
                    "cantidad": cant
                }
        respuesta_data = carrito

    elif accion == "FINALIZAR_COMPRA":
        productos_carrito = CLIENTE_CARRITOS.get(cliente_id, {})
        if not productos_carrito:
            respuesta_status = "ERROR"; respuesta_data = "El carrito está vacío."
        else:
            total = 0.0
            ticket = []
            
            # Proceso de compra y descuento de stock
            for id, cant in productos_carrito.items():
                # Validación de stock
                if cant > INVENTARIO[id]['stock']:
                    respuesta_status = "ERROR"; respuesta_data = f"Stock agotado para ID {id}. No se pudo completar la compra."
                    CLIENTE_CARRITOS[cliente_id] = {} # Vaciamos el carrito
                    break
                
                producto_data = INVENTARIO[id]
                subtotal = producto_data['precio'] * cant
                total += subtotal
                
                ticket.append({
                    "nombre": producto_data['nombre'],
                    "cantidad": cant,
                    "subtotal": subtotal
                })
                
                # Descontamos el stock y lo marcamos para guardar
                INVENTARIO[id]['stock'] -= cant
            
            if respuesta_status == "OK":
                guardar_inventario() # Guardamos los cambios al JSON
                CLIENTE_CARRITOS[cliente_id] = {} # Vaciamos el carrito
                respuesta_data = {
                    "tipo": "TICKET", 
                    "items": ticket,
                    "total": total,
                    "mensaje": "¡Gracias por su compra!"
                }
    
    else:
        respuesta_status = "ERROR"; respuesta_data = f"Opción no reconocida: {accion}"

    # Enviamos la respuesta
    envio_respuesta(conn, respuesta_status, respuesta_data)

    if accion == "SALIR":
        return True
    return False

def control_cliente(conn):
    # Función de lectura de buffer y reconstrucción de comandos
    cliente_id = conn.fileno()

    try:
        data = conn.recv(BUFFER_SIZE)

        if not data:
            # Si data es vacío, el cliente cerró el socket.
            return True 
        
        # Añadir datos al buffer del cliente
        CLIENT_BUFFERS[cliente_id] += data
        
        should_close = False # Bandera para cerrar conexión si es necesario

        # Procesar mensajes mientras haya saltos de línea
        while b'\n' in CLIENT_BUFFERS[cliente_id]:
            message_bytes, CLIENT_BUFFERS[cliente_id] = CLIENT_BUFFERS[cliente_id].split(b'\n', 1)
            message = message_bytes.decode('utf-8').strip()
            
            if not message:
                # Si el mensaje es solo un salto de línea, lo ignoramos.
                continue

            should_close = procesar_comando(cliente_id, message)
            if should_close:
                break
        
        return should_close

    except ConnectionResetError:
        print(f"[{cliente_id}] conexion cerrada.")
    except Exception as e:
        print(f"Error de lógica o sintaxis en {cliente_id}: {e}")
        envio_respuesta(conn, "ERROR", f"Error al procesar el comando: {e}")
    
    return False

# Función principal del servidor

def main_server():
    # Inicializa el socket de escucha y el bucle principal de select
    global SERVER_SOCKET_FILENO
    cargar_inventario()

    # Creación del socket de escucha
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(MAX_CONNECTIONS)
        print(f"Servidor iniciado en {HOST}:{PORT}... Esperando conexiones.")
    except Exception as e:
        print(f"Error al iniciar el socket: {e}"); sys.exit(1)

    # El socket de escucha se agrega a la lista de monitoreo
    SOCKET_LIST.append(server_socket)

    # Guardamos el identificador del socket de escucha
    SERVER_SOCKET_FILENO = server_socket.fileno()

    # Bucle principal
    while True:
        try:
            readable, _, exceptional = select.select(SOCKET_LIST, [], SOCKET_LIST, 0.5)
            
            # Manejo de sockets con errores excepcionales
            for sock in exceptional:
                sock.close()
                if sock in SOCKET_LIST: SOCKET_LIST.remove(sock)
                if sock.fileno() in CLIENTE_CARRITOS: del CLIENTE_CARRITOS[sock.fileno()]
                if sock.fileno() in CLIENT_BUFFERS: del CLIENT_BUFFERS[sock.fileno()]


            for sock in readable:
                if sock.fileno() == SERVER_SOCKET_FILENO:
                    # El socket de escucha está listo -> Nueva conexión
                    try:
                        client_conn, client_addr = server_socket.accept()
                        print(f"Cliente conectado desde: {client_addr}")
                        SOCKET_LIST.append(client_conn)
                        # Inicializamos el buffer y el carrito para el nuevo cliente
                        CLIENT_BUFFERS[client_conn.fileno()] = b''
                        CLIENTE_CARRITOS[client_conn.fileno()] = {}

                    except Exception as e:
                        print(f"Error al aceptar conexión: {e}")
                else:
                    # Un socket de cliente existente está listo para enviar datos
                    should_close = control_cliente(sock)
                    
                    if should_close:
                        print(f"Cerrando conexión con cliente {sock.fileno()}.")
                        sock.close()
                        if sock in SOCKET_LIST: SOCKET_LIST.remove(sock)
                        if sock.fileno() in CLIENTE_CARRITOS: del CLIENTE_CARRITOS[sock.fileno()]
                        if sock.fileno() in CLIENT_BUFFERS: del CLIENT_BUFFERS[sock.fileno()]


        except KeyboardInterrupt:
            print("\nServidor detenido manualmente.")
            break
        except Exception as e:
            print(f"Error fatal del servidor: {e}")
            break

    # Cierre de recursos
    for sock in SOCKET_LIST:
        try:
            sock.close()
        except:
            pass
    
if __name__ == "__main__":
    main_server()
