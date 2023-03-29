# Eol Report Analytics

Question report in CSV.

# Install

    docker-compose exec lms pip install -e /openedx/requirements/eol_report_analytics
    docker-compose exec lms_worker pip install -e /openedx/requirements/eol_report_analytics

# Install Theme

To enable export Eol Report Analytics button in your theme add next file and/or lines of code:

- _../themes/your_theme/lms/templates/instructor/instructor_dashboard_2/data_download.html_

    **add the script and css**

        <script type="text/javascript" src="${static.url('eol_report_analytics/js/eol_report_analytics.js')}"></script>
        <link rel="stylesheet" type="text/css" href="${static.url('eol_report_analytics/css/eol_report_analytics.css')}"/>

    **and add html button**

          %if 'has_eol_report_analytics' in section_data and section_data['has_eol_report_analytics']:
            <div class='eol_report_analytics-report'>
                <hr>
                <h4 class="hd hd-4">${_("Analítica de preguntas")}</h4>
                <p>
                    <input id="eol_report_analytics_input" type="text" placeholder="block-v1:eol+test100+2021_1+type@problem+block@936f2950368f4eff8dfc4451c865d28c">
                    <input onclick="generate_analytics_report(this)" type="button" name="eol_report_analytics-report" value="${_("Generar")}" data-endpoint="${ section_data['eol_report_analytics_url'] }"/>
                </p>
                <div class="eol_report_analytics-success-msg" id="eol_report_analytics-success-msg"></div>
                <div class="eol_report_analytics-warning-msg" id="eol_report_analytics-warning-msg"></div>
                <div class="eol_report_analytics-error-msg" id="eol_report_analytics-error-msg"></div>
            </div>
        %endif

- In your edx-platform add the following code in the function '_section_data_download' in _edx-platform/lms/djangoapps/instructor/views/instructor_dashboard.py_

        try:
            from eol_report_analytics import views
            section_data['has_eol_report_analytics'] = True
            section_data['eol_report_analytics_url'] = '{}?{}'.format(reverse('eol_report_analytics:data'), urllib.parse.urlencode({'course': str(course_key)}))
        except ImportError:
            section_data['has_eol_report_analytics'] = False

## TESTS
**Prepare tests:**

    > cd .github/
    > docker-compose run lms /openedx/requirements/eol_report_analytics/.github/test.sh
