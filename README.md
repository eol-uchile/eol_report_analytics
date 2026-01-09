# Eol Report Analytics

![Coverage Status](/coverage-badge.svg)

![https://github.com/eol-uchile/eol_report_analytics/actions](https://github.com/eol-uchile/eol_report_analytics/workflows/Python%20application/badge.svg)

Question report in CSV.

# Install

    docker-compose exec lms pip install -e /openedx/requirements/eol_report_analytics
    docker-compose exec lms_worker pip install -e /openedx/requirements/eol_report_analytics

# Install Theme

To enable the export eol report analytics button, add the following code to your theme. This includes a conditional check to ensure the template only renders if the app is installed.

- _../themes/your_theme/lms/templates/instructor/instructor_dashboard_2/data_download.html_

    **add eol_report_analytics template to the data_download template**

        <% 
        eol_report_analytics_url = None
        eol_report_analytics_traceback = None
        try:
          eol_report_analytics_url = reverse('eol_report_analytics:data')
        except Exception as e:
          if settings.DEBUG:
            eol_report_analytics_traceback = traceback.format_exc() 
        %>
        %if eol_report_analytics_traceback:
          <div class="eol_report_analytics_traceback">
            <pre>${eol_report_analytics_traceback}</pre>
          </div>
        %elif eol_report_analytics_url:
          <%include file="eol_report_analytics.html"/>
        %endif

### Adding new translations:

To extract and update any new translatable text, run the update command below. After manually filling in the new translations, run the compile command to update the .mo translation files.

### Commands

**Update**

    docker run -it --rm -w /code -v $(pwd):/code python:3.8 bash
    pip install -r requirements-i18n.in
    make update_translations

**Compile**

    docker run -it --rm -w /code -v $(pwd):/code python:3.8 bash
    pip install -r requirements-i18n.in
    make compile_translations

## TESTS
**Prepare tests:**

- Install **act** following the instructions in [https://nektosact.com/installation/index.html](https://nektosact.com/installation/index.html)

**Run tests:**
- In a terminal at the root of the project
    ```
    act -W .github/workflows/pythonapp.yml
