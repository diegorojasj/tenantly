-- One database per service: no service can read another's tables.
CREATE DATABASE identity;
CREATE DATABASE operations;
CREATE DATABASE billing;
