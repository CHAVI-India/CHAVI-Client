To do a docker based install, download the three files inside a folder and rename them as follows:

| Original File Name | Modified File name |
| ------ | ------ |
| example_docker-compose.yml | docker-compose.yml |
| example_.env | .env |
| example_nginx.conf | nginx.conf |

Ensure that Docker desktop is installed 

After that start the containers with the command 

```bash
docker compose up -d
```

