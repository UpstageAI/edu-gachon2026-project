create table if not exists recipes (
    id serial primary key,
    name text not null,
    cooking_time integer
);

create table if not exists recipe_ingredients (
    recipe_id integer not null references recipes(id),
    ingredient_id integer not null references ingredients_master(id),
    primary key (recipe_id, ingredient_id)
);
