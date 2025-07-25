Docker Installation Method
=============================

This method will install the Chavi application using Docker containers.

Prerequisites
----------------
Docker Desktop:

- Docker Desktop is a platform for building, shipping, and running applications using containers.
- It provides a container runtime, a command line interface, and a platform for building and shipping containerized applications.
- It is available for Windows and macOS.

Please refere to the official Docker documentation for installation instructions:

- `Docker Desktop for Windows <https://docs.docker.com/desktop/install/windows-install/>`_
- `Docker Desktop for macOS <https://docs.docker.com/desktop/install/mac-install/>`_


After Docker Desktop is installed, you can start the Docker application. Please ensure that proxy settings are configured correctly in the Docker Desktop settings. Without this Docker Desktop will not be able to access the internet.

Installation
---------------

Create a folder in a location where the CHAVI client application will be installed.
Inside this folder, create the following three files:

- .env
- docker-compose.yml
- ngnix.conf

The contents of the files are as follows:

.. literalinclude:: ../../docker_install/example_docker-compose.yml
   :language: yaml
..
.. literalinclude:: ../../docker_install/example_nginx.conf
   :language: bash
..
.. literalinclude:: ../../docker_install/example_.env
   :language: bash
..

After these files have been created you can start editing the .env file. Ensure that the password fields are properly set. If a proxy is used for network access, please ensure that the proxy settings are configured correctly in the .env file.

After the .env file has been edited, you can start the Docker containers by running the following command:

.. code-block:: bash

   docker-compose up -d
..

Updating the Software
----------------------

Before any update, please take a backup of the database. To do so please refer to the :ref:`database_backup` page.

Stop all running containers in the Docker Desktop application.

After the backup has been taken, you will have to delete the old image and pull the new image. 

In Docker desktop, please go to the images section and delete the old image for the CHAVI client. After this is deleted, we would suggest also that you delete the volume created for the chaviclient. However DO NOT delete the volume created for the database. 

Once this is done you can pull the new image by running the following command:

.. code-block:: bash

   docker-compose pull
..

After the image has been pulled, you can start the containers by running the following command:

.. code-block:: bash

   docker-compose up -d
..
   


