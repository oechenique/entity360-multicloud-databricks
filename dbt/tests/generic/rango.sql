{# Filas fuera de [min, max] (con nulos permitidos). Reemplaza al CHECK que Iceberg gestionado no admite. #}
{% test rango(model, column_name, min=none, max=none) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and ({% if min is not none %}{{ column_name }} < {{ min }}{% else %}false{% endif %}
       or {% if max is not none %}{{ column_name }} > {{ max }}{% else %}false{% endif %})
{% endtest %}
