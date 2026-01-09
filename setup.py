import setuptools

setuptools.setup(
    name="eol_report_analytics",
    version="2.1.0",
    author="Oficina EOL UChile",
    author_email="eol-ing@uchile.cl",
    description=".",
    url="https://eol.uchile.cl",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    entry_points={
        "lms.djangoapp": ["eol_report_analytics = eol_report_analytics.apps:EolReportAnalyticsConfig"]},
)
