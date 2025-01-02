## Welcome

The CHAVI Client Application is a companion application to the CHAVI de-identification system. This application allows users to enter patient data at their own premsises and this clinical data can then be de-identified in a reporducible fashion. While the application is primarily designed for data entry using the provided forms, it is possible to allow import of data from other sources like CSV and other databases in the future. 

## Database schema

The database schema in the client application mimics the central CHAVI server database with few exceptions related to the user authentication tables. This allows data to be faithfully migrated to the central CHAVI server while retaining the longitudinal temporal linkage. 

## How to Install

First of all ensure that you have the latest version of Python 3 installed in your computer. Please see the official documentation available at https://www.python.org/downloads/ for system specific instructions. If you are using a Linux based system then this may be available in your repository.

Please clone the git repository in your computer. Laowing command.

```
git clone https://gitlab.com/drsantam/chavi_client.git
```


After the repository 