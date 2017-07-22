var gulp = require('gulp'),
    eslint = require('gulp-eslint');

gulp.task('lint', function() {
    return gulp.src('../static/js/call.js')
    .pipe(eslint('.eslintrc.json'))
    .pipe(eslint.format())
});

gulp.task('default', function () {
    return gulp.watch(['../static/js/call.js'], ['lint']);
});
