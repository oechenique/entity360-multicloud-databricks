# entity360-multicloud-databricks

Plataforma que consolida registros públicos reales de empresas (GLEIF desde un legacy en SQL Server
con CDC, SEC EDGAR en AWS, GDELT en GCP, OpenSanctions y Wikidata), resuelve identidades en un golden
record y lo entrega gobernado en Unity Catalog. El README completo (problema, diagrama, el porqué de
cada pieza, métricas y cómo levantarlo) se escribe en el cierre de la fase 10 (`reglas/12`).

## Errores conocidos

### Banco Galicia queda en revisión (resolución de identidades, A059)
La clave `BANCO_GALICIA` del diccionario de alias de GDELT (Banco de Galicia y Buenos Aires, la
subsidiaria de Grupo Financiero Galicia, que no presenta ante la SEC) no trae CIK ni LEI. Sin un
identificador compartido no hereda país (la resolución nunca supone uno) y suma 60 puntos contra el
Banco de Galicia y Buenos Aires de GLEIF: queda en `resolution.revision` (tipo `revisar`). En Gold hay
dos entidades para el mismo banco: la de GLEIF (con su LEI anulado fusionado) y una que solo tiene la
clave de GDELT, y las menciones en noticias (`fct_news_signal`) quedan en la segunda.

Es una decisión, no un descuido: unirla exigía suponer el país AR, y esa suposición es la que unía la
matriz mexicana de Vista con su filial argentina (calibración v1). Bajar el umbral de aceptación a 60 la
resolvería, pero aceptaría también todos los pares que hoy esperan revisión con 60 puntos. Detalle y
números: `databricks/resolucion/calibracion/INFORME.md` (v2.1). Solución prevista: resolverla a mano en
la revisión, o agregar el LEI al diccionario como dato del productor (fase 4), no del matching.
