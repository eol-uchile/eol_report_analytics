function generate_analytics_report(input){
  var success_div = document.getElementById('eol_report_analytics-success-msg');
  var error_div = document.getElementById('eol_report_analytics-error-msg');
  var warning_div = document.getElementById('eol_report_analytics-warning-msg');
  var url = input.dataset.endpoint;
  var errorMessage = 'Error en generar reporte de problemas. Por favor actualice la página e intente de nuevo.';
  var block_id = document.getElementById('eol_report_analytics_input').value;
  if(block_id == ""){
    error_div.textContent = 'Ingrese id del bloque.';
    error_div.style.display = 'block';
    success_div.style.display = 'none';
    warning_div.style.display = 'none';
    return true
  }
  else
  {return $.ajax({
      type: 'GET',
      dataType: 'json',
      url: url+"&block="+ encodeURIComponent(block_id),
      error: function(error) {
          if (error.responseText) {
              errorMessage = JSON.parse(error.responseText);
          }
          error_div.textContent = errorMessage;
          error_div.style.display = 'block';
          success_div.style.display = 'none';
          warning_div.style.display = 'none';
          return true
      },
      success: function(data) {
          if (data.error) {
              error_div.textContent = data.error;
              error_div.style.display = 'block';
              success_div.style.display = 'none';
              warning_div.style.display = 'none';
          }
          else{
              if (data.error_task) {
                  warning_div.textContent = 'El reporte ya se esta generando, por favor espere.';
                  warning_div.style.display = 'block';
                  error_div.style.display = 'none';
                  success_div.style.display = 'none';
              }
              else{
                  success_div.textContent = data.status;
                  success_div.style.display = 'block';
                  warning_div.style.display = 'none';
                  error_div.style.display = 'none';
              }
          }
          return true
      }
  });}
}