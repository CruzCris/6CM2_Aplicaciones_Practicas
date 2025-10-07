# Cliente -> Socket de flujo bloqueante

import socket
import select
import json
import sys
import os
import time
import textwrap

# Configuracion del cliente
HOST = '127.0.0.1'
PUERTO = 9999      
BUFFER_SIZE = 4096

# Variable auxiliar para la acción actual
accion = "" 

# Buffer para reconstruir mensajes del servidor
RECEIVE_BUFFER = b'' 

# Variables de control
FLAG_EXIT = False # Variable para terminar el cliente
FLAG_MENU = True # Variable para controlar el menú

def mostrar_menu():
    # Muestra el menú principal
    menu_text = """
    ==================================================
           TIENDA EN LÍNEA - SOCKETS BLOQUEANTES
    ==================================================
    1.  Ver todos los productos
    2.  Buscar articulos por nombre o marca
    3.  Listar articulos por tipo
    4.  Agregar articulos al carrito de compra
    5.  Editar contenido del carrito de compra
    6.  Ver carrito
    7.  Finalizar compra
    8.  Salir
    --------------------------------------------------
    Escribe el número de la opción que deseas utilizar:
    """
    print(textwrap.dedent(menu_text))
    sys.stdout.flush()

def mostrar_productos(products_data, title="Inventario"):
    # Muestra la lista de productos
    if not products_data:
        print(f"\nNo se encontraron articulos en {title}.")
        return
    
    # El servidor en select devuelve un diccionario, lo convertimos a lista para mostrar
    if isinstance(products_data, dict):
        products_data = products_data.values()

    print("\n" + "="*80)
    print(f"        {title.upper()} ({len(products_data)} articulos)        ")
    
    print("=" * 80)
    print(f"{'ID':<5} {'NOMBRE':<30} {'MARCA':<15} {'TIPO':<10} {'PRECIO':<10} {'STOCK':<8}")
    print("-" * 80)
    
    for product in products_data:
        pid = str(product.get('id', 'N/A'))
        stock_str = str(product.get('stock', 'N/A'))
        print(f"{pid:<5} {product['nombre']:<30} {product['marca']:<15} {product['tipo']:<10} ${product['precio']:<9.2f} {stock_str:<8}")
    print("=" * 80)

def mostrar_carrito(carrito):
    # Muestra el contenido del carrito
    if not carrito:
        print("\nEl carrito de compras esta vacio.")
        return

    print("\n" + "="*60)
    print("              CARRITO DE COMPRAS              ")
    print("-" * 60)
    print(f"{'ID':<5} {'NOMBRE':<30} {'CANT.':<6} {'PRECIO/U':<10} {'SUBTOTAL':<10}")
    print("-" * 60)
    
    total = 0.0
    for id, producto in carrito.items():
        subtotal = producto['precio'] * producto['cantidad']
        total += subtotal
        print(f"{id:<5} {producto['nombre']:<30} {producto['cantidad']:<6} ${producto['precio']:<9.2f} ${subtotal:<9.2f}")

    print("-" * 60)
    print(f"{'TOTAL A PAGAR:':>48} ${total:<10.2f}")
    print("=" * 60)

def mostrar_ticket(ticket):
    # Muestra el ticket de compra
    print("\n\n" + "="*50)
    print("             TICKET DE COMPRA               ")
    print("="*50)
    print(f"Mensaje: {ticket.get('mensaje', 'Compra procesada')}")
    print(f"ID Transacción: {ticket.get('ticket_id', 'N/A')}")
    print("-" * 50)
    print(f"{'ITEM':<35} {'CANT':<6} {'PRECIO':<8}")
    print("-" * 50)

    for producto in ticket['items']:
        print(f"{producto['nombre']:<35} {producto['cantidad']:<6} ${producto['subtotal']:<8.2f}")

    print("-" * 50)
    print(f"{'TOTAL FINAL:':>40} ${ticket['total']:<8.2f}")
    print("=" * 50)
    print("Vuelva pronto!\n")

def manejo_respuesta(respuesta):
    # Se procesa la respuesta recibida del servidor
    global FLAG_EXIT
    
    # Separamos el estado de la respuesta del cuerpo JSON
    partes = respuesta.split(' ', 1)
    respuesta_status = partes[0]
    json_str = partes[1] if len(partes) > 1 else "{}"

    # Deserializamos el JSON
    try:
        respuesta_data = json.loads(json_str)
    except json.JSONDecodeError:
        respuesta_data = f"Error: No se pudo deserializar el JSON de la respuesta"

    # Acciones si el estado es OK
    if respuesta_status == "OK":
        # Diferenciamos el tipo de respuesta por su contenido
        if isinstance(respuesta_data, dict):
            if respuesta_data.get('tipo') == "TICKET":
                mostrar_ticket(respuesta_data)
            # Búsquedas o Listados
            elif any('stock' in p for p in respuesta_data.values()): 
                title = "RESULTADOS DE BÚSQUEDA/LISTADO"
                # Mostrar todo
                if len(respuesta_data) > 3 and all('stock' in p for p in respuesta_data.values()): 
                    title = "RESULTADOS DE BÚSQUEDA/LISTADO"
                mostrar_productos(respuesta_data, title=title)
            # Carrito
            elif all('cantidad' in item for item in respuesta_data.values()):
                mostrar_carrito(respuesta_data)
            # Cualquier otro mensaje
            elif "mensaje" in respuesta_data:
                print(f"\n{respuesta_data['mensaje']}")
            elif "SALIR" in respuesta_data:
                 print("\nDesconexion por el servidor.")
                 FLAG_EXIT = True
            else:
                print(f"\n{respuesta_data}")

    elif respuesta_status == "ERROR":
        print(f"\nError: {respuesta_data}")
    
    else:
        print(f"\nProtocolo desconocido: {respuesta}")

    # Volvemos a mostrar el menú despues de procesar la respuesta
    mostrar_menu()

def recepcion_respuesta(cliente_socket):
    # Maneja la recepción de datos del servidor y reconstruye el buffer
    global RECEIVE_BUFFER
    try:
        
        data = cliente_socket.recv(BUFFER_SIZE)

        if not data:
            print("\nEl servidor cerró la conexión.")
            return True
        
        RECEIVE_BUFFER += data
        
        # Buscamos saltos de línea para delimitar mensajes completos y deserializar
        while b'\n' in RECEIVE_BUFFER:
            respuesta_bytes, RECEIVE_BUFFER = RECEIVE_BUFFER.split(b'\n', 1)
            respuesta = respuesta_bytes.decode('utf-8').strip()
            manejo_respuesta(respuesta)

    except ConnectionResetError:
        print("\nConexión reseteada por el servidor.")
        return True
    except Exception as e:
        print(f"\nError en la recepcion: {e}")
        # Limpiamos el buffer
        RECEIVE_BUFFER = b'' 
        return True # Se cierra la conexión
        
    return False # Conexión sigue abierta

def envio_servidor(cliente_socket, message):
    # Lee la entrada del usuario y envía al servidor
    global accion, FLAG_EXIT
    
    if not message:
        # Si la entrada es vacía, no hacemos nada.
        return False

    comando_params = message.upper().split()
    comando_enviar = ""
    
    # Manejo de el número de la opción del menú
    if not accion and len(comando_params) == 1 and comando_params[0].isdigit():
        opcion = comando_params[0]
        
        if opcion == "1":
            comando_enviar = "VER_PRODUCTOS"
        elif opcion == "2":
            print("-> ¿Que deseas buscar? (nombre o marca)")
            accion = "BUSCAR"
            return False 
        elif opcion == "3":
            print("-> ¿Que tipo de productos deseas listar?")
            accion = "LISTAR"
            return False
        elif opcion == "4":
            print("-> Escribe el ID del producto y la cantidad que deseas agregar (ej: 101 2)")
            accion = "AGREGAR_CARRITO"
            return False
        elif opcion == "5":
            print("-> Escribe el ID del producto y la nueva cantidad (ej: 101 3 || 0 para eliminar)")
            accion = "EDITAR_CARRITO"
            return False
        elif opcion == "6":
            comando_enviar = "VER_CARRITO"
        elif opcion == "7":
            comando_enviar = "FINALIZAR_COMPRA"
        elif opcion == "8":
            comando_enviar = "SALIR"
        else:
            print("No se reconoce la opción. Por favor, intenta de nuevo.")
            return False
    
    # Manejo de parámetros
    elif accion:
        # Validamos que haya parámetros para completar la acción
        if not message.strip():
            print("Debes proporcionar un parámetro para la acción. Intenta de nuevo.")
            return False
            
        comando_enviar = f"{accion} {message.upper()}"
        accion = "" # Reiniciamos el estado

    else:
        print("No se reconoce el comando. Por favor, intenta de nuevo.")
        return False
        

    # Enviamos el comando al servidor
    if comando_enviar:
        try:
            # Aseguramos que el salto de línea vaya al final
            cliente_socket.sendall(comando_enviar.encode('utf-8') + b'\n')
            if comando_enviar == "SALIR":
                FLAG_EXIT = True
        except BrokenPipeError:
            print("\nError: Conexión cerrada por el servidor.")
            return True # Conexión cerrada
        except Exception as e:
            print(f"\nError: No se pudo enviar el comando: {e}")
            return True

    return False # Conexión sigue abierta

def main_client():
    # Establece la conexión y lanza el bucle select
    global FLAG_EXIT, FLAG_MENU
    
    try:
        # Crear socket y conectar al servidor
        cliente_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cliente_socket.connect((HOST, PUERTO))
        print("Conexión establecida con el servidor.")
    except ConnectionRefusedError:
        print(f"\nError: No se pudo conectar a {HOST}:{PUERTO}.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError al conectar: {e}")
        sys.exit(1)
        
    # Lista de monitoreo
    inputs = [cliente_socket]
    
    # Mostramos el menú y establecemos la bandera para la primera entrada
    mostrar_menu()
    
    # Bucle principal
    while not FLAG_EXIT:
        try:
            # Usamos select para esperar datos del socket o entrada del usuario
            readable, _, _ = select.select(inputs, [], [], 0.1)

            # Indicador de error
            FLAG_ERROR = False

            for source in readable:
                if source is cliente_socket:
                    # Hay datos del servidor
                    if recepcion_respuesta(cliente_socket):
                        FLAG_ERROR = True
                        break 
            
            # Verificamos si hay entrada disponible
            if not FLAG_ERROR:
                # Usamos input() para leer de la consola
                try:
                    message = input("--> ").strip()
                    # envio_servidor devuelve True si la conexión se debe cerrar
                    if envio_servidor(cliente_socket, message):
                        FLAG_ERROR = True
                except KeyboardInterrupt:
                    print("\nCliente detenido manualmente.")
                    FLAG_ERROR = True
                except EOFError: # Captura si se presiona Ctrl+Z/Ctrl+D
                    print("\nCliente detenido manualmente (EOF).")
                    FLAG_ERROR = True

            if FLAG_ERROR:
                break

        except KeyboardInterrupt:
            print("\nCliente detenido manualmente.")
            FLAG_EXIT = True
            break
        except Exception as e:
            print(f"\nError inesperado: {e}")
            FLAG_EXIT = True
            break

    # Cerramos la conexión
    print("\nFinalizando conexión...")
    cliente_socket.close()
    sys.exit(0)

if __name__ == "__main__":
    main_client()