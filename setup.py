from setuptools import setup, find_packages

setup(
    name="cuadrada",
    version="1.0.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Flask==3.0.2",
        "Werkzeug==3.0.1",
        "reportlab==4.1.0",
        "python-dotenv==1.0.1",
        "PyMuPDF==1.23.8",
        "openai==1.12.0",
        "anthropic==0.18.1",
        "pymongo==4.6.1",
        "authlib==1.5.2",
        "requests==2.32.3",
        "gunicorn==21.2.0",
        "stripe==7.11.0",
    ],
) 