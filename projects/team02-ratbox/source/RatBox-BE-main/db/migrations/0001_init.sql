create table if not exists ingredients_master (
    id serial primary key,
    name text not null unique
);

create table if not exists ingredient_synonyms (
    id serial primary key,
    ingredient_id integer not null references ingredients_master(id),
    synonym_name text not null
);
