create table if not exists ingredient_substitutes (
    ingredient_id integer not null references ingredients_master(id),
    substitute_id integer not null references ingredients_master(id),
    note text,
    primary key (ingredient_id, substitute_id)
);
