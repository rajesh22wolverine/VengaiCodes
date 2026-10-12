# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (no-AI) Ruby backend: Rails (API only)
#  over Active Record + SQLite
#  ai/codegen_rails.py — The Rails backend codegen_deterministic
#  dispatches to: a complete, runnable API-only Rails app. Per table: a
#  model (app/models/) and a controller (app/controllers/). Shared by
#  every table: ApplicationController (reading a request, answering rows
#  and errors), app/lib (RequestFields, DatabaseErrors, ApiError), the
#  routes, and the config/ a Rails app needs to boot.
#
#  Follows the knowledge registry's Rails rules: conventions (one model
#  per table, <plural>_controller.rb, resources routes), what a column
#  must satisfy declared in its model, database constraints in the
#  migrations too, JSON rendered with an explicit status. One rule is
#  deliberately not followed: strong parameters. permit() silently drops
#  a value of the wrong kind and can't say "left out" from "wrong", and
#  the contract every generated backend keeps is to name every such
#  field; so a request's JSON is read field by field against the model's
#  FIELDS (app/lib/request_fields.rb), and Rails' own JSON body parser is
#  switched off so a body that isn't a JSON object gets the API's 400
#  rather than a parse error raised before any controller runs.
#
#  Same REST surface as every other generated backend: /api/<table> and
#  /api/<table>/<id>, JSON keyed by column name, PUT changes only the
#  fields it sends, every problem with a request reported at once, the
#  database's constraint violations answered with the same sentences.
#  Errors are {"error": ...}, which the screens read.
#
#  The schema is owned by real Active Record migrations in the migration
#  DSL (migrations_rails), applied with `bin/rails db:migrate`.
#
#  Values are stored as the other SQLite backends store them, so a
#  CHECK's literal compares correctly as text: Rails drops the fraction
#  of a whole-second time ("09:30:00", which sorts before
#  "09:30:00.000000"), so every date-time attribute is declared with a
#  type that always writes six digits (config/initializers).
#
#  Names. Ruby has one namespace for constants, shared with Ruby itself,
#  Rails and every gem, and Active Record defines a method per column:
#    - A model can't be called anything that is already a constant
#      (File, Data, Set, Rails, …): RESERVED_CONSTANTS, which the
#      toolchain test compares with a booted app's real constants.
#    - A column can't be called anything Active Record already defines
#      on a record (save, errors, changed, …) or would define for
#      another column: RESERVED_ATTRIBUTES, checked the same way.
#    - Nothing here calls a method named after a column: values are read
#      and written through record[...] and record.attributes, and
#      controllers refer to models as ::Book.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re

from app.ai import db_schema, migrations_rails
from app.ai.codegen_shared import GeneratedFile
from app.ai.migrations_rails import camelize, ruby_str

APP_MODULE = "GeneratedApp"
# Rails 8.1 is the supported release line; it needs Ruby 3.2 or newer.
RAILS_VERSION = "8.1"
RUBY_REQUIREMENT = ">= 3.2"
DEFAULT_PORT = 3000

# Constants the generated app itself defines.
_OWN_CONSTANTS = frozenset(
    {
        "ApiError",
        "ApplicationController",
        "ApplicationRecord",
        "DatabaseErrors",
        APP_MODULE,
        "RequestFields",
        "StoredDateTime",
    }
)
# Top-level constants of Ruby, Rails and the app's gems (without the ones
# that have an underscore, which no table name can produce). A model with
# one of these names would reopen that class or module instead of being a
# model. Kept complete by tests/unit/test_rails_e2e.py, which compares it
# with what a booted generated app really defines.
RESERVED_CONSTANTS = frozenset(
    """
    AbstractController ActionController ActionDispatch ActionPack ActionView ActiveModel ActiveRecord
    ActiveSupport Addrinfo Arel ARGF ArgumentError ARGV Array Base64 BasicObject BasicSocket Benchmark
    BigDecimal BigMath Binding Bundler CGI Class ClosedQueueError Comparable Complex Concurrent
    ConditionVariable Crass Data Date DateAndTime DateTime Delegator DidYouMean Digest Dir Encoding
    EncodingError Enumerable Enumerator ENV EOFError ERB Errno ErrorHighlight Erubi Etc Exception
    FalseClass Fiber FiberError File FileTest FileUtils Float FloatDomainError Forwardable FrozenError
    GC Gem Hash HashWithIndifferentAccess I18n IndexError Integer Interrupt IO IOError IPAddr IPSocket
    JSON Kernel KeyError LCSDiff LoadError LocalJumpError Logger Loofah Marshal MatchData Math Method
    Mime Module Monitor MonitorMixin Mutex NameError NilClass Nokogiri NoMatchingPatternError
    NoMatchingPatternKeyError NoMemoryError NoMethodError NotImplementedError Numeric Object ObjectSpace
    Open3 OpenSSL ParseError Pathname Prism Proc Process Psych Puma Queue Racc Rack Ractor
    RactorLocalSingleton Rails Random Range RangeError Rational RbConfig Refinement Regexp RegexpError
    RubyVM RuntimeError ScanError ScriptError SecureRandom SecurityError Set Shellwords Signal
    SignalException SimpleDelegator SingleForwardable Singleton SizedQueue Socket SocketError SortedSet
    SQLite3 StandardError STDERR STDIN STDOUT StopIteration String StringIO StringScanner Struct Symbol
    SyntaxError SyntaxSuggest SystemCallError SystemExit SystemStackError TCPServer TCPSocket Tempfile
    Thor Thread ThreadError ThreadGroup Time Timeout TracePoint TrueClass TSort TypeError TZInfo
    UDPSocket UnboundMethod UncaughtThrowError UnicodeNormalize UNIXServer UNIXSocket URI Warning
    WeakRef YAML Zeitwerk ZeroDivisionError Zlib
    """.split()
)

# Names Active Record defines on every record, or would define for a column
# of that name (an attribute "x" also gets x_was, x_changed?, restore_x!, …
# so a column can't be named so that one of those already exists). Kept
# complete by tests/unit/test_rails_e2e.py the same way.
RESERVED_ATTRIBUTES = frozenset(
    """
    accessed_fields add_to_transaction aggregate_reflections all_attributes_for_inspect
    all_timestamp_attributes_in_model allow_destroy apply_scoping around_save_collection_association
    assign_attributes assign_multiparameter_attributes
    assign_nested_attributes_for_collection_association
    assign_nested_attributes_for_one_to_one_association assign_nested_parameter_attributes
    assign_to_or_mark_for_destruction associated_records_to_validate_or_save association
    association_cached association_foreign_key association_foreign_key_changed association_instance_get
    association_instance_set association_valid attribute attribute_aliases attribute_before_last_save
    attribute_before_type_cast attribute_came_from_user attribute_change attribute_change_to_be_saved
    attribute_changed attribute_changed_in_place attribute_for_database attribute_for_inspect
    attribute_in_database attribute_method attribute_method_patterns attribute_missing attribute_names
    attribute_names_for_partial_inserts attribute_names_for_partial_updates
    attribute_names_for_serialization attribute_present attribute_previous attribute_previous_change
    attribute_previously attribute_previously_changed attribute_previously_was attribute_was
    attribute_writer_missing attributes attributes_before_type_cast attributes_for_create
    attributes_for_database attributes_for_inspect attributes_for_update attributes_in_database
    attributes_with_values automatic_scope_inversing automatically_invert_plural_associations
    autosaving_belongs_to_for becomes build_decrypt_attribute_assignments
    build_encrypt_attribute_assignments cache_key cache_key_with_version cache_timestamp_format
    cache_version cache_versioning call_reject_if can_use_fast_cache_version
    cant_modify_encrypted_attributes_when_frozen changed changed_attribute_names_to_save
    changed_attributes changed_for_autosave changes changes_applied changes_to_save ciphertext_for class
    clear_attribute clear_attribute_change clear_attribute_changes clear_changes_information
    clear_timestamp_attributes clear_transaction_record_state clone collection_cache_versioning
    column_for_attribute compute_primary_key connection connection_handler context_for_validation
    counter_cached_association_names create_or_update current_time_from_proper_timezone
    custom_inspect_method_defined custom_validation_context decrement decrypt decrypt_attributes
    default_connection_handler default_role default_scope_override default_scopes default_shard
    default_validation_context defined_enums delete deprecated_associations_api_guard destroy
    destroy_association_async_batch_size destroy_association_async_job destroy_associations destroy_row
    destroyed destroyed_by_association display dup encode_with encrypt encrypt_attributes
    encrypted_attribute encrypted_attributes ensure_proper_type errors
    execute_callstack_for_multiparameter_attributes extract_callstack_for_multiparameter_attributes
    find_parameter_position find_record_by_id forget_attribute_assignments format_for_inspect freeze
    from_json frozen full_inspect generate_token_for halted_callback_hook has_attribute
    has_changes_to_save has_defer_touch_attrs has_destroy_flag has_encrypted_attributes
    has_transactional_callbacks hash id id_before_type_cast id_for_database id_in_database id_was
    include_root_in_json increment init_attributes init_internals init_with init_with_attributes
    initialize_internals_callback inspect inspect_with_attributes inspection_filter invalid
    inverse_polymorphic_association inverse_polymorphic_association_changed lock lock_optimistically
    locking_enabled logger mark_for_destruction marked_for_destruction marshal_dump marshal_load
    matched_attribute_method max_updated_column_timestamp method methods missing_attribute model_name
    mutations mutations_before_last_save mutations_from_database nested_attributes_options
    nested_records_changed_for_autosave new_record no_touching normalize_attribute
    normalize_changed_in_place_attributes normalized_attribute_changed_in_place normalized_attributes
    param_delimiter partial_inserts partial_updates perform_validations persisted pk_attribute
    pluralize_table_names populate_with_current_scope_attributes pretty_print previous_changes
    previously_new_record previously_persisted primary_key_prefix_type primary_key_values_present
    query_attribute query_cast_attribute raise_validation_error raw_timestamp_to_cache_version
    read_attribute read_attribute_before_type_cast read_attribute_for_database
    read_attribute_for_serialization read_attribute_for_validation read_store_attribute readonly
    record_timestamps record_update_timestamps reject_new_record reload
    remember_transaction_record_state report_deprecated_association respond_to_without_attributes
    restore_attributes restore_transaction_record_state run_callbacks sanitize_for_mass_assignment
    sanitize_forbidden_attributes save save_belongs_to_association save_collection_association
    save_has_one_association saved_change_to_attribute saved_changes send serializable_add_includes
    serializable_attributes serializable_hash should_record_timestamps signed_id
    signed_id_verifier_secret skip_time_zone_conversion_for_attributes slice store_accessor_for
    store_full_class_name store_full_sti_class strict_loaded_associations strict_loading
    strict_loading_all strict_loading_mode strict_loading_n_plus_one_only surreptitiously_touch
    table_name_prefix table_name_suffix time_zone_aware_attributes time_zone_aware_types
    timestamp_attributes_for_create_in_model timestamp_attributes_for_update_in_model to_ary to_key
    to_model to_partial_path toggle touch touch_deferred_attributes touch_later transaction
    transaction_include_any_action trigger_transactional_callbacks type type_cast_attribute_value
    type_for_attribute update update_attribute update_column update_columns valid validate
    validate_belongs_to_association validate_collection_association validate_encryption_allowed
    validate_has_one_association validates_absence_of validates_acceptance_of validates_comparison_of
    validates_confirmation_of validates_exclusion_of validates_format_of validates_inclusion_of
    validates_length_of validates_numericality_of validates_presence_of validates_size_of validates_with
    validating_belongs_to_for validation_context values_at verify_readonly_attribute will_be_destroyed
    will_save_change_to_attribute with_lock with_transaction_returning_status write_attribute
    write_store_attribute
    """.split()
)

# How a request value is read for a column (RequestFields).
_KINDS = {
    "string": "string",
    "text": "string",
    "integer": "integer",
    "float": "float",
    "decimal": "decimal",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "json": "json",
}


# ───────────────────────────────────────────────
#  Text helpers
# ───────────────────────────────────────────────
def doc(text: str) -> str:
    """User text on one comment line."""
    line = " ".join(str(text or "").split())
    return "".join(ch for ch in line if ch.isprintable()).replace("TODO", "to-do")


_TOKEN = re.compile(r"__([A-Z_]+?)__")


def _fill(template: str, **values: str) -> str:
    """Every __TOKEN__ replaced in one pass, so a value (a table's label,
    say) that happens to contain a token's text is left as written."""
    return _TOKEN.sub(lambda m: values[m.group(1)], template)


def controller_class(sql_name: str) -> str:
    return f"{camelize(sql_name)}Controller"


def name_problems(schema: db_schema.ResolvedSchema) -> list[str]:
    problems = []
    for t in schema.tables:
        if t.class_name in RESERVED_CONSTANTS or t.class_name in _OWN_CONSTANTS:
            problems.append(
                f'The table "{t.name}" would produce a class named {t.class_name}, which Ruby, Rails or '
                "the generated app already defines — rename the table in Architecture."
            )
        elif t.class_name.endswith("Controller"):
            problems.append(
                f'The table "{t.name}" would produce a model named {t.class_name}, a name Rails keeps '
                "for controllers — rename the table in Architecture."
            )
        elif camelize(t.slug) != t.class_name:
            # Rails loads app/models/<slug>.rb expecting exactly this constant.
            problems.append(
                f'The table "{t.name}" can\'t be given a model file Rails would load as {t.class_name} '
                "— rename the table in Architecture."
            )
        for c in t.columns:
            if c.column in RESERVED_ATTRIBUTES:
                problems.append(
                    f'The field "{c.name}" in "{t.name}" has a name Active Record already uses on every '
                    f"record ({c.column}) — rename it in Architecture."
                )
        for chk in t.checks:
            why = migrations_rails.check_problem(chk.sql)
            if why:
                problems.append(
                    f'The rule "{chk.name}" on "{t.name}" can\'t be kept by Rails on SQLite: {why} '
                    "— reword it in Architecture."
                )
    return problems


def _base(col: dict, tables: dict) -> dict:
    """A foreign key column has the type of the column it points at."""
    fk = col.get("fk")
    if not fk:
        return col
    if fk["column"] == "id":
        return {"type": "integer", "length": None}
    return _base(tables[fk["table"]]["columns"][fk["column"]], tables)


def _restrict_message(sql_name: str, snapshot: dict) -> str:
    blockers = sorted(
        {
            other["label"]
            for other in snapshot["tables"].values()
            for col in other["columns"].values()
            if col["fk"]
            and col["fk"]["table"] == sql_name
            and col["fk"]["on_delete"] == "restrict"
        }
    )
    if blockers:
        return f"Can't delete this record: {', '.join(blockers)} still refer to it."
    return "Can't delete this record: other records still refer to it."


# ───────────────────────────────────────────────
#  app/models/<table>.rb
# ───────────────────────────────────────────────
def model_file(
    t: db_schema.ResolvedTable,
    snapshot: dict,
    heading: str,
    class_names: dict[str, str],
) -> GeneratedFile:
    tables = snapshot["tables"]
    table = tables[t.sql_name]
    label = doc(table["label"])
    datetimes = []
    fields = []
    for c in table["column_order"]:
        col = table["columns"][c]
        base = _base(col, tables)
        kind = base["type"]
        if kind == "datetime":
            datetimes.append(c)
        parts = [
            f"kind: :{_KINDS[kind]}",
            f"null: {'true' if col['nullable'] else 'false'}",
            f"default: {'true' if col['default'] else 'false'}",
        ]
        if kind == "string" and base.get("length"):
            parts.append(f"limit: {base['length']}")
        if col["fk"]:
            fk = col["fk"]
            parts.append(
                "references: { "
                f"model: {ruby_str(class_names[fk['table']])}, column: {ruby_str(fk['column'])}, "
                f"label: {ruby_str(tables[fk['table']]['label'])}"
                " }"
            )
        fields.append(f"    {ruby_str(c)} => {{ {', '.join(parts)} }},")
    attributes = [
        f"  attribute :{c}, :stored_datetime"
        for c in [*datetimes, "created_at", "updated_at"]
    ]
    field_lines = (
        ["  FIELDS = {", *fields, "  }.freeze"] if fields else ["  FIELDS = {}.freeze"]
    )
    lines = [
        f"# {doc(heading)}",
        "#",
        "# Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "# call). The table is created and changed by the migrations in db/migrate/",
        "# (`bin/rails db:migrate`).",
        f"class {t.class_name} < ApplicationRecord",
        f"  self.table_name = {ruby_str(t.sql_name)}",
        "",
        "  # Date-times are stored as UTC text with six fractional digits, the form the",
        "  # migrations' checks and defaults compare (config/initializers/stored_date_time.rb).",
        *attributes,
        "",
        "  # What a request may send for each column and what it has to satisfy; read",
        "  # by RequestFields (app/lib/request_fields.rb).",
        *field_lines,
        "",
        f"  # VENGAI:CUSTOM:{t.slug}_model:start",
        f"  # Add associations, scopes and methods for {label} here. A new column belongs",
        "  # in the Architecture tab instead, so a migration adds it to the database.",
        "  # This block is preserved across future regenerations.",
        f"  # VENGAI:CUSTOM:{t.slug}_model:end",
        "end",
        "",
    ]
    return GeneratedFile(
        path=f"backend/app/models/{t.slug}.rb",
        language="ruby",
        content="\n".join(lines),
        description=f"Deterministic model for {t.name}",
    )


# ───────────────────────────────────────────────
#  app/controllers/<tables>_controller.rb
# ───────────────────────────────────────────────
_CONTROLLER_RB = """# REST routes for __TITLE__ — the paths the generated screens call.
# Deterministically generated by VengaiCode (no AI call); what every table's
# controller shares is in ApplicationController and app/lib.
class __CONTROLLER__ < ApplicationController
  LABEL = __LABEL__
  RESTRICT_MESSAGE = __RESTRICT__

  def index
    render json: rows(::__MODEL__.order(:id))
  end

  def show
    render json: row(find_record(::__MODEL__, LABEL))
  end

  def create
    record = ::__MODEL__.new
    RequestFields.fill(record, request_body, creating: true)
    record.save!
    # Answered as stored.
    render json: row(record.reload), status: :created
  end

  # Changes only the fields the request sends, like the other generated backends.
  def update
    record = find_record(::__MODEL__, LABEL)
    RequestFields.fill(record, request_body, creating: false)
    record[:updated_at] = Time.current
    record.save!
    render json: row(record.reload)
  end

  # A 404 when the row isn't there, a 409 when other rows still need it.
  def destroy
    record = find_record(::__MODEL__, LABEL)
    begin
      record.destroy!
    rescue ActiveRecord::InvalidForeignKey
      raise ApiError.new(409, RESTRICT_MESSAGE)
    end
    head :no_content
  end

  # VENGAI:CUSTOM:__SLUG___routes:start
  # Add custom, non-CRUD actions here (and their routes in config/routes.rb).
  # This block is preserved across regenerations.
  # VENGAI:CUSTOM:__SLUG___routes:end
end
"""


def controller_file(t: db_schema.ResolvedTable, snapshot: dict) -> GeneratedFile:
    return GeneratedFile(
        path=f"backend/app/controllers/{t.sql_name}_controller.rb",
        language="ruby",
        content=_fill(
            _CONTROLLER_RB,
            TITLE=doc(t.name),
            CONTROLLER=controller_class(t.sql_name),
            MODEL=t.class_name,
            LABEL=ruby_str(snapshot["tables"][t.sql_name]["label"]),
            RESTRICT=ruby_str(_restrict_message(t.sql_name, snapshot)),
            SLUG=t.slug,
        ),
        description=f"REST routes for {t.name}",
    )


_APPLICATION_CONTROLLER_RB = """# What every table's controller shares: reading a request, answering rows and
# answering errors. Written by VengaiCode.
class ApplicationController < ActionController::API
  # Requests are read by request_body below, not wrapped by Rails.
  wrap_parameters false

  # Every failure answers {"error": "..."} with its HTTP status, which is what
  # the generated screens show.
  rescue_from ApiError do |problem|
    render json: { error: problem.message }, status: problem.status
  end

  # A refusal by the database, explained.
  rescue_from ActiveRecord::StatementInvalid do |failure|
    problem = DatabaseErrors.explain(failure.message)
    render json: { error: problem.message }, status: problem.status
  end

  private

  # The request's JSON object; a 400 for anything else.
  def request_body
    body = begin
      JSON.parse(request.raw_post)
    rescue JSON::ParserError, EncodingError
      nil
    end
    raise ApiError.new(400, 'Send the record as a JSON object.') unless body.is_a?(Hash)

    body
  end

  # The row the path's :id names; a 400 when that isn't a number, a 404 when no
  # row has it.
  def find_record(model, label)
    id = params[:id].to_s
    raise ApiError.new(400, 'id: not a valid id') unless id.match?(/\\A-?[0-9]+\\z/)

    model.find_by(id: id.to_i) || raise(ApiError.new(404, "#{label} #{id.to_i} not found."))
  end

  def rows(records)
    records.map { |record| row(record) }
  end

  # A row as the API answers it: keyed by column name, numbers as numbers,
  # date-times as RFC 3339 UTC ("2024-01-31T09:30:00Z").
  def row(record)
    record.attributes.transform_values do |value|
      case value
      when BigDecimal then value.to_f
      when Time, ActiveSupport::TimeWithZone then value.utc.iso8601(6).sub(/\\.?0+Z\\z/, 'Z')
      when Date then value.iso8601
      else value
      end
    end
  end
end
"""

_APPLICATION_RECORD_RB = """# What every model inherits. Written by VengaiCode.
class ApplicationRecord < ActiveRecord::Base
  primary_abstract_class
end
"""

_API_ERROR_RB = """# A failure with the HTTP status to answer it with; ApplicationController turns
# one into {"error": "..."}. Written by VengaiCode.
class ApiError < StandardError
  attr_reader :status

  def initialize(status, message)
    super(message)
    @status = status
  end
end
"""

_REQUEST_FIELDS_RB = """# Reads a request's JSON into a record, field by field, against the model's
# FIELDS. Written by VengaiCode.
#
# Every field is checked first, and every problem is reported at once as one
# 422; every foreign key has to point at a row that exists; only then are the
# fields the request sent set. A request may leave a field out (the default
# applies, or an update keeps the value) or send it as null — a Ruby Hash from
# JSON keeps the two apart.
module RequestFields
  # Digits a decimal keeps, and how many of them follow the point.
  DECIMAL_DIGITS = __DIGITS__
  DECIMAL_PLACES = __PLACES__

  NOT_A_DECIMAL = 'expected a number like 12.50'
  DATE_TIME = /\\A(\\d{4})-(\\d{2})-(\\d{2})[T ](\\d{2}):(\\d{2})(?::(\\d{2})(\\.\\d{1,9})?)?(Z|[+-]\\d{2}:\\d{2})?\\z/

  # A value of the wrong kind.
  class Mismatch < StandardError; end

  module_function

  def fill(record, body, creating:)
    fields = record.class::FIELDS
    problems = []
    values = {}
    fields.each do |name, field|
      next unless body.key?(name)

      values[name] = body[name].nil? ? nil : parse(field[:kind], body[name])
    rescue Mismatch => e
      problems << "#{name}: #{e.message}"
    end
    fields.each do |name, field|
      sent = body.key?(name)
      unless field[:null]
        if sent && body[name].nil?
          problems << "#{name}: may not be null"
        elsif creating && !sent && !field[:default]
          problems << "#{name}: is required"
        end
      end
      if field[:limit] && values[name].is_a?(String) && values[name].length > field[:limit]
        problems << "#{name}: at most #{field[:limit]} characters"
      end
    end
    raise ApiError.new(422, problems.join("\\n")) if problems.any?

    fields.each do |name, field|
      target = field[:references]
      next if target.nil? || values[name].nil?
      next if Object.const_get(target[:model]).exists?(target[:column] => values[name])

      raise ApiError.new(422, "#{name}: no row in #{target[:label]} has #{target[:column]} #{values[name]}.")
    end
    values.each do |name, value|
      record[name] = value
      # An explicit null on create is stored, not replaced by the column's default.
      record.send(:attribute_will_change!, name) if creating && value.nil?
    end
  end

  def parse(kind, value)
    case kind
    when :string
      value.is_a?(String) ? value : raise(Mismatch, 'expected text')
    when :integer
      value.is_a?(Integer) && value.bit_length < 64 ? value : raise(Mismatch, 'expected a whole number')
    when :float
      value.is_a?(Numeric) && value.to_f.finite? ? value.to_f : raise(Mismatch, 'expected a number')
    when :boolean
      [true, false].include?(value) ? value : raise(Mismatch, 'expected true or false')
    when :decimal then decimal(value)
    when :date then date(value)
    when :datetime then date_time(value)
    else value
    end
  end

  # A fixed-point number: a JSON number, or text like "12.50".
  def decimal(value)
    text =
      case value
      when String then value.strip
      when Integer then value.to_s
      when Float then value.finite? ? BigDecimal(value.to_s).to_s('F') : ''
      else ''
      end
    match = /\\A-?([0-9]+)(?:\\.([0-9]+))?\\z/.match(text) || raise(Mismatch, NOT_A_DECIMAL)
    if match[2].to_s.sub(/0+\\z/, '').length > DECIMAL_PLACES
      raise Mismatch, "only #{DECIMAL_PLACES} decimal places are stored"
    end
    raise Mismatch, 'number is too large' if match[1].sub(/\\A0+/, '').length > DECIMAL_DIGITS - DECIMAL_PLACES

    BigDecimal(text)
  end

  # A date: "2024-01-31".
  def date(value)
    match = value.is_a?(String) && /\\A(\\d{4})-(\\d{2})-(\\d{2})\\z/.match(value.strip)
    raise ArgumentError unless match

    Date.new(match[1].to_i, match[2].to_i, match[3].to_i)
  rescue ArgumentError
    raise Mismatch, 'expected a date like 2024-01-31'
  end

  # A date-time: RFC 3339 ("2024-01-31T09:30:00Z", any offset), or without an
  # offset, read as UTC. Kept in UTC, to the microsecond it is stored with.
  def date_time(value)
    match = value.is_a?(String) && DATE_TIME.match(value.strip)
    raise ArgumentError unless match

    year, month, day, hour, minute, second = match.captures.first(6).map(&:to_i)
    offset = match[8].nil? || match[8] == 'Z' ? '+00:00' : match[8]
    Time.new(year, month, day, hour, minute, second + "0#{match[7]}".to_r, offset).utc.floor(6)
  rescue ArgumentError
    raise Mismatch, 'expected a date and time like 2024-01-31T09:30:00Z'
  end
end
"""

_DATABASE_ERRORS_RB = """# What a refusal by the database means, so a violated constraint comes back as
# a sentence instead of a raw database error. Written by VengaiCode.
module DatabaseErrors
  # (its name in the database's message, HTTP status, sentence). Longest names
  # first.
  CONSTRAINTS = [
__CONSTRAINTS__  ].freeze

  module_function

  def explain(text)
    if text.include?('UNIQUE constraint failed') || text.include?('CHECK constraint failed')
      # SQLite names a failed UNIQUE by its columns, a failed CHECK by its name.
      CONSTRAINTS.each do |key, status, message|
        return ApiError.new(status, message) if names?(text, key)
      end
    end
    column = text[/NOT NULL constraint failed: (\\S+)/, 1]
    return ApiError.new(422, "#{column}: may not be null") if column
    if text.include?('FOREIGN KEY constraint failed')
      return ApiError.new(422, "A record this one refers to doesn't exist.")
    end

    ApiError.new(409, "The database refused this change: #{text}")
  end

  # Whether the message names key whole, not as part of a longer name.
  def names?(text, key)
    text.match?(/(?<![[:alnum:]_.])#{Regexp.escape(key)}(?![[:alnum:]_.])/)
  end
end
"""


def shared_files(constraints: list[tuple[str, int, str]]) -> list[GeneratedFile]:
    entries = "".join(
        f"    [{ruby_str(k)}, {s}, {ruby_str(m)}],\n"
        for k, s, m in sorted(constraints, key=lambda e: -len(e[0]))
    )
    return [
        GeneratedFile(
            path="backend/app/controllers/application_controller.rb",
            language="ruby",
            content=_APPLICATION_CONTROLLER_RB,
            description="What every controller shares: reading requests, answering rows and errors",
        ),
        GeneratedFile(
            path="backend/app/models/application_record.rb",
            language="ruby",
            content=_APPLICATION_RECORD_RB,
            description="What every model inherits",
        ),
        GeneratedFile(
            path="backend/app/lib/api_error.rb",
            language="ruby",
            content=_API_ERROR_RB,
            description="A failure with the HTTP status to answer it with",
        ),
        GeneratedFile(
            path="backend/app/lib/request_fields.rb",
            language="ruby",
            content=_fill(
                _REQUEST_FIELDS_RB,
                DIGITS=str(db_schema.DECIMAL_PRECISION),
                PLACES=str(db_schema.DECIMAL_SCALE),
            ),
            description="Reads and checks a request's fields against the model's FIELDS",
        ),
        GeneratedFile(
            path="backend/app/lib/database_errors.rb",
            language="ruby",
            content=_fill(_DATABASE_ERRORS_RB, CONSTRAINTS=entries),
            description="What each database constraint means",
        ),
    ]


# ───────────────────────────────────────────────
#  config/, bin/ and the Gemfile (the Rails adapter's migrations mode)
# ───────────────────────────────────────────────
_GEMFILE = """source 'https://rubygems.org'

ruby '__RUBY__'

gem 'rails', '~> __RAILS__.0'
gem 'sqlite3', '>= 2.1'
gem 'puma', '>= 6.0'
# Lets the screens call the API from another origin (config/initializers/cors.rb).
gem 'rack-cors'
# Windows has no time zone database of its own.
gem 'tzinfo-data', platforms: %i[windows jruby]
"""

_RAKEFILE = """require_relative 'config/application'

Rails.application.load_tasks
"""

_CONFIG_RU = """require_relative 'config/environment'

run Rails.application
Rails.application.load_server
"""

_BIN_RAILS = """#!/usr/bin/env ruby
APP_PATH = File.expand_path('../config/application', __dir__)
require_relative '../config/boot'
require 'rails/commands'
"""

_BOOT_RB = """ENV['BUNDLE_GEMFILE'] ||= File.expand_path('../Gemfile', __dir__)

require 'bundler/setup' # Set up the gems listed in the Gemfile.
"""

_APPLICATION_RB = """# __TITLE__ API, written by VengaiCode.
#
# `bin/rails db:migrate` applies the database migrations and `bin/rails server`
# serves the API on port __PORT__ (set PORT to change it). The database is SQLite:
# storage/<environment>.sqlite3, or the file DATABASE_PATH names.
require_relative 'boot'

require 'rails'
require 'active_model/railtie'
require 'active_record/railtie'
require 'action_controller/railtie'

Bundler.require(*Rails.groups)

module __MODULE__
  class Application < Rails::Application
    config.load_defaults __RAILS__
    # JSON in, JSON out: no views, cookies or sessions.
    config.api_only = true
  end
end
"""

_ENVIRONMENT_RB = """require_relative 'application'

Rails.application.initialize!
"""

_DEVELOPMENT_RB = """Rails.application.configure do
  # Code is reloaded when it changes, so the server doesn't need a restart.
  config.enable_reloading = true
  config.eager_load = false
  config.consider_all_requests_local = true
  # Fail loudly when a migration hasn't been run yet.
  config.active_record.migration_error = :page_load
end
"""

_PRODUCTION_RB = """Rails.application.configure do
  config.enable_reloading = false
  config.eager_load = true
  config.consider_all_requests_local = false
  config.log_level = :info
  # Set SECRET_KEY_BASE in the environment (`bin/rails secret` makes one).
end
"""

_DATABASE_YML = """# SQLite. Set DATABASE_PATH to keep the database somewhere else.
default: &default
  adapter: sqlite3
  pool: <%= ENV.fetch("RAILS_MAX_THREADS") { 3 } %>
  timeout: 5000
  database: <%= ENV.fetch("DATABASE_PATH") { "storage/#{Rails.env}.sqlite3" } %>

development:
  <<: *default

test:
  <<: *default

production:
  <<: *default
"""

_PUMA_RB = """threads_count = ENV.fetch('RAILS_MAX_THREADS', 3)
threads threads_count, threads_count
port ENV.fetch('PORT', __PORT__)
# `bin/rails restart` touches tmp/restart.txt.
plugin :tmp_restart
pidfile ENV['PIDFILE'] if ENV['PIDFILE']
"""

_CORS_RB = """# The screens may call the API from another origin (a packaged app's window
# isn't the API's origin).
Rails.application.config.middleware.insert_before 0, Rack::Cors do
  allow do
    origins '*'
    resource '*', headers: :any, methods: %i[get post put patch delete options]
  end
end
"""

_JSON_BODIES_RB = """# Controllers read a request's JSON themselves (ApplicationController#request_body),
# so a body that isn't a JSON object gets the API's own 400 and its sentence.
# Left on, Rails' parser would raise on such a body before any controller runs.
ActionDispatch::Request.parameter_parsers = ActionDispatch::Request.parameter_parsers.except(:json)
"""

_STORED_DATE_TIME_RB = """# Date-times are stored as UTC text with six fractional digits ("2024-01-31
# 09:30:00.000000") — the form the migrations' checks and defaults use — so they
# compare correctly as text. Rails itself drops the fraction of a whole-second
# time, and "09:30:00" sorts before "09:30:00.000000"; every model declares its
# date-time attributes with this type instead.
class StoredDateTime < ActiveRecord::Type::DateTime
  def serialize_cast_value(value)
    time = super
    time.respond_to?(:strftime) ? time.utc.strftime('%Y-%m-%d %H:%M:%S.%6N') : time
  end
end

ActiveRecord::Type.register(:stored_datetime, StoredDateTime)
"""

_ROUTES_RB = """Rails.application.routes.draw do
  message = { message: __MESSAGE__ }.to_json
  root to: ->(_env) { [200, { 'content-type' => 'application/json' }, [message]] }

  # /api/<table> and /api/<table>/:id for every table.
  scope 'api' do
__RESOURCES__
    # VENGAI:CUSTOM:extra_routes:start
    # Add routes for custom actions here, e.g.
    # get 'books/export', to: 'books#export'
    # This block is preserved across regenerations.
    # VENGAI:CUSTOM:extra_routes:end
  end
end
"""


def routes_file(schema: db_schema.ResolvedSchema, project_name: str) -> GeneratedFile:
    resources = "".join(
        f"    resources :{t.sql_name}, only: %i[index show create update destroy]\n"
        for t in schema.tables
    )
    return GeneratedFile(
        path="backend/config/routes.rb",
        language="ruby",
        content=_fill(
            _ROUTES_RB,
            MESSAGE=ruby_str(f"{project_name} API is running"),
            RESOURCES=resources,
        ),
        description="Routes: /api/<table> and /api/<table>/:id for every table",
    )


def manifest_files() -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="backend/Gemfile",
            language="ruby",
            content=_fill(_GEMFILE, RUBY=RUBY_REQUIREMENT, RAILS=RAILS_VERSION),
            description="Ruby dependency manifest",
        ),
        GeneratedFile(
            path="backend/config/database.yml",
            language="yaml",
            content=_DATABASE_YML,
            description="Database connection settings (SQLite)",
        ),
    ]


def entry_point_files(project_name: str) -> list[GeneratedFile]:
    def ruby(path: str, content: str, description: str) -> GeneratedFile:
        return GeneratedFile(
            path=f"backend/{path}",
            language="ruby",
            content=content,
            description=description,
        )

    return [
        ruby("Rakefile", _RAKEFILE, "Loads the app's rake tasks (db:migrate, …)"),
        ruby("config.ru", _CONFIG_RU, "Rack entry point"),
        ruby("bin/rails", _BIN_RAILS, "The `rails` command for this app"),
        ruby("config/boot.rb", _BOOT_RB, "Sets up the gems"),
        ruby(
            "config/application.rb",
            _fill(
                _APPLICATION_RB,
                TITLE=doc(project_name),
                PORT=str(DEFAULT_PORT),
                MODULE=APP_MODULE,
                RAILS=RAILS_VERSION,
            ),
            "Rails application configuration",
        ),
        ruby("config/environment.rb", _ENVIRONMENT_RB, "Boots the application"),
        ruby(
            "config/environments/development.rb",
            _DEVELOPMENT_RB,
            "Development settings",
        ),
        ruby(
            "config/environments/production.rb",
            _PRODUCTION_RB,
            "Production settings",
        ),
        ruby(
            "config/puma.rb",
            _fill(_PUMA_RB, PORT=str(DEFAULT_PORT)),
            "Web server settings",
        ),
        ruby("config/initializers/cors.rb", _CORS_RB, "Allows cross-origin calls"),
        ruby(
            "config/initializers/json_bodies.rb",
            _JSON_BODIES_RB,
            "Leaves reading JSON bodies to the controllers",
        ),
        ruby(
            "config/initializers/stored_date_time.rb",
            _STORED_DATE_TIME_RB,
            "The fixed-width date-time attribute type",
        ),
    ]


def backend_files(
    schema: db_schema.ResolvedSchema,
    project_name: str,
    constraints: list[tuple[str, int, str]],
    headings: dict[str, str],
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    """(model files, other backend files) — the first backend file is
    config/routes.rb, which the wiring context calls the routes file."""
    snapshot = db_schema.snapshot(schema)
    class_names = {t.sql_name: t.class_name for t in schema.tables}
    models = [
        model_file(t, snapshot, headings[t.sql_name], class_names)
        for t in schema.tables
    ]
    backend = [
        routes_file(schema, project_name),
        *[controller_file(t, snapshot) for t in schema.tables],
        *shared_files(constraints),
    ]
    return models, backend
