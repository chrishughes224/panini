CREATE MIGRATION m1jxidxgnwly6bkfoirnbsulebdf5gegxvvjrpkql2r3hte5xwpmzq
    ONTO initial
{
  CREATE SCALAR TYPE default::StickerKind EXTENDING enum<Special, Generic, Promo, Team>;
  CREATE FUTURE no_linkful_computed_splats;
  CREATE TYPE default::Sticker {
      CREATE REQUIRED PROPERTY sort_order: std::int32;
      CREATE INDEX ON (.sort_order);
      CREATE REQUIRED PROPERTY code: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE REQUIRED PROPERTY kind: default::StickerKind;
      CREATE PROPERTY team_code: std::str;
  };
  CREATE TYPE default::User {
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET default := (std::datetime_current());
      };
      CREATE REQUIRED PROPERTY email: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE REQUIRED PROPERTY password_hash: std::str;
      CREATE REQUIRED PROPERTY username: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
  };
  CREATE TYPE default::CollectionEntry {
      CREATE REQUIRED LINK sticker: default::Sticker;
      CREATE REQUIRED LINK user: default::User;
      CREATE CONSTRAINT std::exclusive ON ((.user, .sticker));
      CREATE INDEX ON (.user);
      CREATE REQUIRED PROPERTY quantity: std::int16 {
          SET default := 1;
          CREATE CONSTRAINT std::min_value(1);
      };
      CREATE REQUIRED PROPERTY updated_at: std::datetime {
          SET default := (std::datetime_current());
      };
  };
  CREATE TYPE default::Session {
      CREATE REQUIRED PROPERTY token: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE INDEX ON (.token);
      CREATE REQUIRED LINK user: default::User;
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET default := (std::datetime_current());
      };
      CREATE REQUIRED PROPERTY expires_at: std::datetime;
  };
};
