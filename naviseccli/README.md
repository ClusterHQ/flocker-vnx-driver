# naviseccli

A Docker image for running ``naviseccli``:

* https://github.com/emc-openstack/naviseccli/

## Build the image

```
docker build --tag clusterhq/naviseccli .
```

## Add User Security Keys

* Remove any existing security keys

```
docker run --rm \
       --volume $HOME/keys:/keys
       clusterhq/naviseccli
       -removeusersecurity
```

* Create new keys


```
docker run --rm \
       --net host \
       --volume $HOME/keys:/keys \
       clusterhq/naviseccli \
       -addusersecurity -scope 0 -user <USER> -password <PASSWORD>
```

Alternatively, you can type the password  interactively by running the container as follows:

```
docker run -it --rm \
       --net host \
       --volume $HOME/keys:/keys \
       clusterhq/naviseccli
       -addusersecurity -scope 0 -user <USERNAME>
```

## List all LUNs

```
docker run --rm \
       --net host \
       --volume $HOME/keys:/keys \
       clusterhq/naviseccli \
       lun -list
```

## List all storage groups

```
docker run --rm \
       --net host \
       --volume $HOME/keys:/keys \
       clusterhq/naviseccli \
       storagegroup -list
```

## Create an Alias

```
alias "naviseccli=docker run --rm --net host --volume $HOME/keys:/keys clusterhq/naviseccli"
naviseccli lun -list
```

## CLI Reference

 * http://www.emc.com/collateral/support-training/support/069001038-navisphere-cli.pdf
