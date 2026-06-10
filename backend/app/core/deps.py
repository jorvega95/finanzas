"""Dependencias FastAPI: usuario actual y espacio activo.

GLO-05: toda query filtra por space_id. ESP-03: permisos por rol.
Usuario sin membresía en el espacio solicitado => 404 (no 403),
para no filtrar existencia (caso de prueba 8 de REGLAS_NEGOCIO.md).
"""
